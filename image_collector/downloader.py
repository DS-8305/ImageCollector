"""Bounded image transport, decoding, normalization and exact pixel deduplication."""
from __future__ import annotations

import base64
import binascii
from email.utils import parsedate_to_datetime
import hashlib
import io
import re
import time
from urllib.parse import urljoin, urlsplit
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
import requests
from urllib3.exceptions import ReadTimeoutError

from .models import (Candidate, Cancelled, DownloadedImage, DuplicateImage,
                     DownloadBudgetExceeded, RejectedImage, ResolvedOptions)
from .budget import ActiveBudget


MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_DATA_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 40_000_000
ENGINE_REFERERS = {"naver": "https://search.naver.com/", "google": "https://www.google.com/"}


class _Retryable(Exception):
    def __init__(self, reason: str, delay: float | None = None):
        super().__init__(reason)
        self.delay = delay


class Downloader:
    def __init__(self, options: ResolvedOptions, stop_event=None, session=None, deadline=None):
        self.options = options
        self.stop_event = stop_event
        self.budget = ActiveBudget(options.keyword_timeout)
        self.deadline = time.monotonic() + options.keyword_timeout if deadline is None else deadline
        self._owns_session = session is None
        self.session = requests.Session() if session is None else session
        self._closed = False

    @property
    def deadline(self):
        return self.budget.deadline

    @deadline.setter
    def deadline(self, value):
        self.budget.deadline = value

    def close(self):
        if self._owns_session and not self._closed:
            self.session.close()
        self._closed = True

    def _check_budget(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise Cancelled("Image download cancelled")
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise DownloadBudgetExceeded("Image download deadline exceeded")

    def _timeout(self):
        self._check_budget()
        return 20.0 if self.deadline is None else min(20.0, max(0.001, self.deadline - time.monotonic()))

    def _wait(self, seconds):
        self._check_budget()
        if self.deadline is not None and time.monotonic() + seconds >= self.deadline:
            raise DownloadBudgetExceeded("Download retry cannot fit within deadline")
        end = time.monotonic() + seconds
        while True:
            self._check_budget()
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            interval = min(0.05, remaining)
            if self.stop_event is None:
                time.sleep(interval)
            else:
                self.stop_event.wait(interval)

    @staticmethod
    def _http_url(url):
        if not isinstance(url, str) or not url or any(ord(char) <= 32 for char in url):
            raise RejectedImage("Missing or invalid HTTP(S) image URL")
        try:
            parsed = urlsplit(url)
            if (parsed.scheme not in ("http", "https") or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None):
                raise ValueError("unsupported address or embedded credentials")
            parsed.port  # Validate malformed and out-of-range ports.
        except ValueError as exc:
            raise RejectedImage("Unsupported or invalid HTTP(S) image URL") from exc
        return url

    def download(self, candidate: Candidate, seen_hashes=None) -> DownloadedImage:
        self._check_budget()
        mode = self.options.download_mode
        if mode == "thumbnail":
            return self._download(candidate, candidate.thumbnail_url, "thumbnail", seen_hashes)
        try:
            return self._download(candidate, candidate.original_url, "original", seen_hashes)
        except (DuplicateImage, DownloadBudgetExceeded):
            raise  # Neither duplicates nor exhausted budgets allow a thumbnail fallback.
        except RejectedImage as exc:
            if mode != "original-preferred":
                raise
            self._check_budget()
            return self._download(candidate, candidate.thumbnail_url, "thumbnail", seen_hashes, str(exc))

    def _download(self, candidate, url, kind, seen_hashes, fallback_reason=""):
        self._check_budget()
        if kind == "thumbnail" and isinstance(url, str) and url.startswith("data:"):
            body = self._data_image(url)
            actual_url = url
        else:
            self._http_url(url)
            referer = ENGINE_REFERERS.get(candidate.engine or self.options.engine, "")
            if kind == "original":
                try:
                    referer = self._http_url(candidate.source_url)
                except RejectedImage:
                    referer = ""
            body, actual_url = self._http_image(url, referer)
        normalized, width, height = self._normalize(body)
        self._check_budget()
        # Dimensions prevent ambiguous byte concatenations across different image shapes.
        digest = hashlib.sha256(f"{width}x{height}:".encode() + normalized.tobytes()).hexdigest()
        if seen_hashes is not None and digest in seen_hashes:
            raise DuplicateImage("Identical image pixels already saved")
        output = io.BytesIO()
        normalized.save(output, "PNG")
        self._check_budget()
        return DownloadedImage(output.getvalue(), width, height, digest, actual_url, kind, fallback_reason)

    def _data_image(self, url):
        prefix, separator, payload = url.partition(",")
        if not separator or not re.fullmatch(r"data:image/(jpeg|png|webp);base64", prefix, re.IGNORECASE):
            raise RejectedImage("Unsupported data image: JPEG, PNG and WebP base64 thumbnails only")
        if len(payload) > ((MAX_DATA_BYTES + 2) // 3) * 4:
            raise RejectedImage("Data thumbnail exceeds 2MB byte limit")
        try:
            body = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RejectedImage("Invalid base64 thumbnail") from exc
        if len(body) > MAX_DATA_BYTES:
            raise RejectedImage("Data thumbnail exceeds 2MB byte limit")
        return body

    @staticmethod
    def _retry_delay(header):
        try:
            seconds = float(header)
        except (TypeError, ValueError):
            try:
                seconds = parsedate_to_datetime(header).timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                seconds = 0.25
        return max(0.0, seconds)

    @staticmethod
    def _is_read_timeout(exc):
        # requests wraps streamed urllib3 read timeouts in ConnectionError.
        stack = [exc]
        visited = set()
        while stack:
            current = stack.pop()
            if id(current) in visited:
                continue
            visited.add(id(current))
            if isinstance(current, ReadTimeoutError):
                return True
            stack.extend(item for item in getattr(current, "args", ()) if isinstance(item, BaseException))
            stack.extend(item for item in (current.__cause__, current.__context__) if item is not None)
        return False

    def _http_image(self, url, referer):
        for attempt in range(3):
            self._check_budget()
            try:
                return self._http_attempt(url, referer)
            except _Retryable as exc:
                reason, delay = str(exc), exc.delay
            except requests.Timeout as exc:
                reason, delay = f"Image download timeout: {exc}", None
            except ReadTimeoutError as exc:
                reason, delay = f"Image download read timeout: {exc}", None
            except requests.ConnectionError as exc:
                if not self._is_read_timeout(exc):
                    self._check_budget()
                    raise RejectedImage(f"Image download connection failed: {exc}") from exc
                reason, delay = f"Image download read timeout: {exc}", None
            except requests.RequestException as exc:
                self._check_budget()
                raise RejectedImage(f"Image download request failed: {exc}") from exc
            self._check_budget()
            if attempt == 2:
                raise RejectedImage(reason)
            self._wait(0.25 * (attempt + 1) if delay is None else delay)
        raise AssertionError("Unreachable download attempt")

    def _http_attempt(self, url, referer):
        headers = {"User-Agent": "Mozilla/5.0 ImageCollector/2.0", "Accept": "image/*"}
        if referer:
            headers["Referer"] = referer
        current_url = url
        for redirects in range(6):
            self._check_budget()
            # Preparing outside Session avoids session cookies, Authorization and netrc.
            # The adapter also avoids Session.send's hidden redirect-body consumption.
            request = requests.Request("GET", self._http_url(current_url), headers=headers).prepare()
            settings = self.session.merge_environment_settings(request.url, {}, True, None, None)
            response = self.session.get_adapter(request.url).send(request, timeout=self._timeout(), **settings)
            try:
                self._check_budget()
                if response.status_code in (301, 302, 303, 307, 308):
                    if redirects == 5 or not response.headers.get("Location"):
                        raise RejectedImage("Image redirect limit or missing redirect target")
                    current_url = self._http_url(urljoin(current_url, response.headers["Location"]))
                    continue
                status = response.status_code
                if status == 429:
                    raise _Retryable("Image HTTP 429 rate limit", self._retry_delay(response.headers.get("Retry-After")))
                if 500 <= status <= 599:
                    raise _Retryable(f"Image HTTP {status}")
                if status != 200:
                    raise RejectedImage(f"Image HTTP {status}")
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if mime and not mime.startswith("image/") and mime not in ("application/octet-stream", "binary/octet-stream"):
                    raise RejectedImage(f"Non-image Content-Type: {mime}")
                try:
                    declared_size = int(response.headers.get("Content-Length", "0"))
                except ValueError:
                    declared_size = 0
                if declared_size > MAX_DOWNLOAD_BYTES:
                    raise RejectedImage("Image exceeds 20MB byte limit")
                body = bytearray()
                # read1 returns available bytes after one socket read, unlike
                # iter_content's 64KiB fill, so a slow drip cannot hide stop/budget.
                def chunks():
                    while True:
                        self._check_budget()
                        chunk = response.raw.read1(64 * 1024, decode_content=True)
                        if not chunk:
                            return
                        yield chunk
                for chunk in chunks():
                    self._check_budget()
                    if len(body) + len(chunk) > MAX_DOWNLOAD_BYTES:
                        raise RejectedImage("Image exceeds 20MB byte limit")
                    body.extend(chunk)
                self._check_budget()
                return bytes(body), response.url
            finally:
                response.close()
        raise RejectedImage("Image redirect limit")

    def _normalize(self, body):
        self._check_budget()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(body)) as image:
                    if image.format not in ("JPEG", "PNG", "WEBP"):
                        raise RejectedImage("Unsupported image format: JPEG, PNG and WebP only")
                    if image.width * image.height > MAX_PIXELS:
                        raise RejectedImage("Image exceeds 40MP pixel limit")
                    image.verify()
                with Image.open(io.BytesIO(body)) as image:
                    image.load()
                    normalized = ImageOps.exif_transpose(image).convert("RGBA")
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
                Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise RejectedImage(f"Invalid or unsafe image: {exc}") from exc
        self._check_budget()
        width, height = normalized.size
        if not self.options.accepts_size(width, height):
            raise RejectedImage(f'이미지 크기 {width}×{height}px가 저장 조건을 충족하지 않습니다. '
                                f'적용 기준: {self.options.size_requirement_text()}')
        return normalized, width, height
