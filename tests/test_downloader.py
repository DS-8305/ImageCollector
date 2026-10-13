"""Downloader behavior against a real local HTTP server and generated images."""
import base64
from collections import Counter
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import io
import struct
import threading
import time
import unittest
from unittest.mock import patch
import zlib

from PIL import Image
import requests

from image_collector.models import Candidate, Cancelled, CollectionOptions, DuplicateImage, RejectedImage


def image_bytes(size=(200, 150), fmt="PNG", **kwargs):
    buffer = io.BytesIO()
    Image.new("RGB", size, (20, 50, 90)).save(buffer, fmt, **kwargs)
    return buffer.getvalue()


class DownloadTests(unittest.TestCase):

    def test_retry_after_longer_than_keyword_budget_does_not_resubmit(self):
        url=self.route("/long-retry",status=429,headers={"Retry-After":"3600"})
        started=time.monotonic()
        with self.assertRaises(RejectedImage):
            self.downloader(deadline=started+6).download(self.candidate(url))
        self.assertEqual(self.hits["/long-retry"],1)
        self.assertLess(time.monotonic()-started,1)

    def test_retry_outside_budget_never_triggers_preferred_thumbnail_fallback(self):
        original = self.route("/budget-original", status=429, headers={"Retry-After": "3600"})
        thumbnail = self.route("/budget-thumbnail")
        options = replace(self.options, download_mode="original-preferred")
        downloader = self.downloader(options=options, deadline=time.monotonic() + 6)
        with self.assertRaisesRegex(RejectedImage, "deadline"):
            downloader.download(self.candidate(original, thumbnail))
        self.assertEqual(self.hits["/budget-original"], 1)
        self.assertEqual(self.hits["/budget-thumbnail"], 0)


    def test_slow_drip_body_honors_cancel_before_large_chunk_fills(self):
        stop=threading.Event()
        def drip(stream):
            for _ in range(100):
                stream.write(b"x")
                stream.flush()
                time.sleep(.02)
        url=self.route("/drip-cancel",body=drip)
        timer=threading.Timer(.12,stop.set)
        timer.start()
        started=time.monotonic()
        try:
            with self.assertRaises(Cancelled):
                self.downloader(stop_event=stop).download(self.candidate(url))
        finally:
            timer.cancel()
        self.assertLess(time.monotonic()-started,.8)

    def test_slow_drip_body_honors_total_deadline(self):
        def drip(stream):
            for _ in range(100):
                stream.write(b"x")
                stream.flush()
                time.sleep(.02)
        url=self.route("/drip-deadline",body=drip)
        started=time.monotonic()
        with self.assertRaises(RejectedImage):
            self.downloader(deadline=started+.12).download(self.candidate(url))
        self.assertLess(time.monotonic()-started,.8)

    @classmethod
    def setUpClass(cls):
        cls.routes = {}
        cls.hits = Counter()
        cls.headers = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                cls.hits[self.path] += 1
                cls.headers[self.path] = dict(self.headers)
                route = cls.routes[self.path]
                if callable(route):
                    route = route(cls.hits[self.path])
                status, headers, body = route
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                try:
                    if callable(body):
                        body(self.wfile)
                    else:
                        self.wfile.write(body)
                except (ConnectionError, OSError):
                    pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.hits.clear()
        self.headers.clear()
        self.routes.clear()
        self.options = CollectionOptions(engine="google", min_long_edge=0).resolve()

    def downloader(self, **kwargs):
        try:
            module = importlib.import_module("image_collector.downloader")
        except ImportError as exc:
            self.fail(f"Downloader contract missing: {exc}")
        options = kwargs.pop("options", self.options)
        downloader = module.Downloader(options, **kwargs)
        self.addCleanup(downloader.close)
        return downloader

    def route(self, name="/image", body=None, status=200, headers=None):
        self.routes[name] = (status, {"Content-Type": "image/png"} if headers is None else headers,
                             image_bytes() if body is None else body)
        return self.base + name

    def candidate(self, original="", thumbnail=""):
        return Candidate(thumbnail, source_url="https://publisher.example/page", original_url=original,
                         engine="google")

    def test_original_is_converted_to_rgba_png_and_records_actual_url(self):
        url = self.route(body=image_bytes(fmt="JPEG"), headers={"Content-Type": "image/jpeg"})
        result = self.downloader().download(self.candidate(url))
        with Image.open(io.BytesIO(result.png_bytes)) as output:
            self.assertEqual((output.format, output.mode, output.size), ("PNG", "RGBA", (200, 150)))
        self.assertEqual((result.width, result.height, result.download_kind, result.downloaded_url),
                         (200, 150, "original", url))
        self.assertEqual(result.fallback_reason, "")
        self.assertEqual(self.headers["/image"]["Referer"], "https://publisher.example/page")

    def test_thumbnail_mode_skips_original_and_uses_engine_referer(self):
        thumb = self.route("/thumb")
        original = self.route("/original")
        options = replace(self.options, download_mode="thumbnail", engine="naver")
        result = self.downloader(options=options).download(replace(self.candidate(original, thumb), engine="naver"))
        self.assertEqual(result.download_kind, "thumbnail")
        self.assertEqual(self.hits["/original"], 0)
        self.assertEqual(self.headers["/thumb"]["Referer"], "https://search.naver.com/")

    def test_preferred_records_http_failure_and_uses_thumbnail(self):
        original = self.route("/original", status=403)
        thumb = self.route("/thumb")
        result = self.downloader(options=replace(self.options, download_mode="original-preferred")).download(
            self.candidate(original, thumb))
        self.assertEqual(result.download_kind, "thumbnail")
        self.assertIn("403", result.fallback_reason)
        self.assertEqual(self.hits["/original"], 1)
        self.assertEqual(self.headers["/thumb"]["Referer"], "https://www.google.com/")

    def test_original_only_never_uses_thumbnail_on_invalid_or_failed_original(self):
        thumb = self.route("/thumb")
        for original in ("", "blob:abc", "file:///test.png", "x-raw-image://abc", "http://user:secret@example.com/x",
                         "https://", self.route("/missing", status=404)):
            with self.subTest(original=original), self.assertRaises(RejectedImage):
                self.downloader().download(self.candidate(original, thumb))
        self.assertEqual(self.hits["/thumb"], 0)
        self.assertEqual(self.hits["/missing"], 1)

    def test_preferred_missing_original_is_explicit_fallback(self):
        result = self.downloader(options=replace(self.options, download_mode="original-preferred")).download(
            self.candidate(thumbnail=self.route()))
        self.assertTrue(result.fallback_reason)
        self.assertEqual(result.download_kind, "thumbnail")

    def test_data_thumbnail_supported_formats_and_original_rejected(self):
        for fmt, mime in (("PNG", "png"), ("JPEG", "jpeg"), ("WEBP", "webp")):
            with self.subTest(fmt=fmt):
                url = f"data:image/{mime};base64," + base64.b64encode(image_bytes(fmt=fmt)).decode()
                result = self.downloader(options=replace(self.options, download_mode="thumbnail")).download(
                    self.candidate(thumbnail=url))
                self.assertEqual((result.width, result.height), (200, 150))
                with self.assertRaises(RejectedImage):
                    self.downloader().download(self.candidate(original=url))

    def test_data_thumbnail_rejects_invalid_or_over_two_megabytes(self):
        downloader = self.downloader(options=replace(self.options, download_mode="thumbnail"))
        for url in ("data:image/svg+xml;base64,AAAA", "data:image/png;base64,***", "data:image/png,abc",
                    "data:image/png;base64," + base64.b64encode(b"x" * (2 * 1024 * 1024 + 1)).decode()):
            with self.subTest(prefix=url[:50]), self.assertRaises(RejectedImage):
                downloader.download(self.candidate(thumbnail=url))

    def test_pixel_duplicate_across_urls_does_not_mutate_seen_hashes(self):
        downloader = self.downloader()
        seen = set()
        first = downloader.download(self.candidate(self.route("/first")), seen)
        self.assertEqual(seen, set())
        seen.add(first.content_hash)
        with self.assertRaises(DuplicateImage):
            downloader.download(self.candidate(self.route("/second", body=image_bytes(compress_level=0))), seen)
        self.assertEqual(seen, {first.content_hash})

    def test_same_pixels_different_dimensions_are_not_duplicate(self):
        downloader = self.downloader()
        a = downloader.download(self.candidate(self.route("/a", image_bytes((200, 150)))))
        b = downloader.download(self.candidate(self.route("/b", image_bytes((150, 200)))), {a.content_hash})
        self.assertNotEqual(a.content_hash, b.content_hash)

    def test_hash_matches_persisted_rgba_dimensions_contract(self):
        result = self.downloader().download(self.candidate(self.route()))
        # Storage/resume contracts prefix normalized RGBA bytes with ASCII dimensions.
        self.assertEqual(result.content_hash, "d6a3a9323fb57de600c505a115bd55cbe8177119ff8fec98fd90029698cb6f2d")

    def test_actual_size_and_orientation_are_checked_without_upscaling(self):
        cases = [("blog", (1200, 150), True), ("blog", (1199, 150), False),
                 ("blog", (1200, 149), False), ("video-landscape", (1920, 1080), True),
                 ("video-landscape", (1080, 1920), False), ("video-portrait", (1080, 1920), True),
                 ("video-portrait", (1920, 1080), False)]
        for index, (profile, size, accepted) in enumerate(cases):
            options = CollectionOptions(engine="google", profile=profile).resolve()
            downloader = self.downloader(options=options)
            url = self.route(f"/size{index}", image_bytes(size))
            with self.subTest(profile=profile, size=size):
                if accepted:
                    result = downloader.download(self.candidate(url))
                    self.assertEqual((result.width, result.height), size)
                else:
                    with self.assertRaises(RejectedImage):
                        downloader.download(self.candidate(url))

    def test_exif_orientation_applied_before_dimensions(self):
        exif = Image.Exif()
        exif[274] = 6
        options = replace(self.options, min_width=150, min_height=200)
        url = self.route(body=image_bytes((200, 150), "JPEG", exif=exif), headers={"Content-Type": "image/jpeg"})
        result = self.downloader(options=options).download(self.candidate(url))
        self.assertEqual((result.width, result.height), (150, 200))

    def test_fallback_still_obeys_minimum_size(self):
        url = self.route(body=image_bytes((200, 150)))
        options = CollectionOptions(engine="google", download_mode="original-preferred").resolve()
        with self.assertRaises(RejectedImage):
            self.downloader(options=options).download(self.candidate(thumbnail=url))

    def test_html_corrupt_unsupported_or_wrong_declared_text_is_rejected(self):
        cases = [(b"<html>error</html>", "text/html"), (b"<html>error</html>", "image/png"),
                 (image_bytes(), "text/plain"), (b"broken", "image/png"),
                 (image_bytes(fmt="GIF"), "image/gif"), (image_bytes()[:-20], "image/png")]
        for index, (body, mime) in enumerate(cases):
            with self.subTest(mime=mime, index=index), self.assertRaises(RejectedImage):
                self.downloader().download(self.candidate(self.route(f"/bad{index}", body, headers={"Content-Type": mime})))

    def test_generic_or_missing_content_type_requires_valid_decode(self):
        for index, headers in enumerate(({}, {"Content-Type": "application/octet-stream"})):
            result = self.downloader().download(self.candidate(self.route(f"/generic{index}", headers=headers)))
            self.assertEqual(result.width, 200)

    def test_stream_limit_enforced_without_content_length(self):
        url = self.route(body=b"x" * (20 * 1024 * 1024 + 1), headers={})
        with self.assertRaisesRegex(RejectedImage, "20|byte|large|limit"):
            self.downloader().download(self.candidate(url))

    def test_content_length_over_limit_is_rejected_before_body_read(self):
        url = self.route(body=b"", headers={"Content-Length": str(20 * 1024 * 1024 + 1)})
        with self.assertRaisesRegex(RejectedImage, "20|byte|large|limit"):
            self.downloader().download(self.candidate(url))

    def test_pixel_limit_checked_before_expensive_decode(self):
        ihdr = struct.pack(">IIBBBBB", 8000, 5001, 8, 2, 0, 0, 0)
        chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
        body = b"\x89PNG\r\n\x1a\n" + chunk + b"\x00\x00\x00\x00IEND\xaeB`\x82"
        with self.assertRaisesRegex(RejectedImage, "pixel|40|dimension"):
            self.downloader().download(self.candidate(self.route(body=body)))

    def test_5xx_retries_three_attempts_and_can_succeed(self):
        url = self.route()
        self.routes["/image"] = lambda count: (503 if count < 3 else 200, {"Content-Type": "image/png"}, image_bytes())
        result = self.downloader().download(self.candidate(url))
        self.assertEqual(result.width, 200)
        self.assertEqual(self.hits["/image"], 3)

    def test_5xx_exhaustion_is_bounded(self):
        with self.assertRaisesRegex(RejectedImage, "503"):
            self.downloader().download(self.candidate(self.route(status=503)))
        self.assertEqual(self.hits["/image"], 3)

    def test_429_retry_after_zero_then_success(self):
        url = self.route()
        self.routes["/image"] = lambda count: (429, {"Retry-After": "0"}, b"") if count < 2 else (200, {}, image_bytes())
        result = self.downloader().download(self.candidate(url))
        self.assertEqual(result.width, 200)
        self.assertEqual(self.hits["/image"], 2)

    def test_cancel_during_retry_after_never_falls_back(self):
        stop = threading.Event()
        # Keep this wait inside the total budget; over-budget waits have a
        # separate regression test and now correctly stop before sleeping.
        original = self.route("/original", status=429, headers={"Retry-After": "1"})
        thumb = self.route("/thumb")
        timer = threading.Timer(0.05, stop.set)
        timer.start()
        self.addCleanup(timer.cancel)
        start = time.monotonic()
        with self.assertRaises(Cancelled):
            self.downloader(options=replace(self.options, download_mode="original-preferred"), stop_event=stop).download(
                self.candidate(original, thumb))
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(self.hits["/thumb"], 0)

    def test_already_cancelled_makes_no_network_request(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(Cancelled):
            self.downloader(stop_event=stop).download(self.candidate(self.route()))
        self.assertEqual(self.hits["/image"], 0)

    def test_expired_deadline_makes_no_network_request(self):
        with self.assertRaises(RejectedImage):
            self.downloader(deadline=time.monotonic() - 1).download(self.candidate(self.route()))
        self.assertEqual(self.hits["/image"], 0)

    def test_deadline_bounds_retry_after(self):
        start = time.monotonic()
        with self.assertRaises(RejectedImage):
            self.downloader(deadline=start + 0.1).download(self.candidate(
                self.route(status=429, headers={"Retry-After": "10000"})))
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(self.hits["/image"], 1)

    def test_redirect_records_actual_url_and_does_not_forward_sensitive_session_state(self):
        destination = self.route("/destination")
        origin = self.route("/origin", status=302, headers={"Location": destination, "Set-Cookie": "private=secret; Path=/"})
        session = requests.Session()
        session.auth = ("name", "secret")
        session.headers.update({"Authorization": "Bearer secret", "Cookie": "session=secret"})
        session.cookies.set("secret", "yes", domain="127.0.0.1")
        self.addCleanup(session.close)
        result = self.downloader(session=session).download(self.candidate(origin))
        self.assertEqual(result.downloaded_url, destination)
        for path in ("/origin", "/destination"):
            self.assertNotIn("Authorization", self.headers[path])
            self.assertNotIn("Cookie", self.headers[path])

    def test_redirect_body_is_not_loaded_or_decoded(self):
        def irrelevant_body(stream):
            time.sleep(0.3)
            stream.write(b"irrelevant redirect body")

        destination = self.route("/destination")
        origin = self.route("/origin", body=irrelevant_body, status=302,
                            headers={"Location": destination, "Content-Length": "999999999"})
        result = self.downloader(deadline=time.monotonic() + 0.1).download(self.candidate(origin))
        self.assertEqual(result.downloaded_url, destination)

    def test_cancel_during_stream_is_cancelled_without_fallback(self):
        stop = threading.Event()

        def body(stream):
            stream.write(b"x" * 65536)
            stream.flush()
            stop.set()
            stream.write(b"y" * 65536)

        original = self.route("/original", body=body)
        thumb = self.route("/thumb")
        options = replace(self.options, download_mode="original-preferred")
        with self.assertRaises(Cancelled):
            self.downloader(options=options, stop_event=stop).download(self.candidate(original, thumb))
        self.assertEqual(self.hits["/thumb"], 0)

    def test_deadline_during_stream_is_honored_without_fallback(self):
        def body(stream):
            stream.write(b"x" * 65536)
            stream.flush()
            time.sleep(0.1)
            stream.write(b"y" * 65536)

        original = self.route("/original", body=body)
        thumb = self.route("/thumb")
        start = time.monotonic()
        options = replace(self.options, download_mode="original-preferred")
        with self.assertRaisesRegex(RejectedImage, "deadline"):
            self.downloader(options=options, deadline=start + 0.04).download(self.candidate(original, thumb))
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(self.hits["/thumb"], 0)

    def test_streamed_read_timeout_is_retried_three_times(self):
        def slow_body(stream):
            time.sleep(0.06)
            stream.write(image_bytes())

        url = self.route()
        self.routes["/image"] = lambda count: (200, {}, slow_body if count < 3 else image_bytes())
        downloader = self.downloader()
        with patch.object(downloader, "_timeout", return_value=0.02):
            result = downloader.download(self.candidate(url))
        self.assertEqual(result.width, 200)
        self.assertEqual(self.hits["/image"], 3)

    def test_connection_timeouts_retry_and_response_is_closed_after_header_rejection(self):
        # A connect timeout cannot be induced reliably on localhost; fault the real adapter boundary.
        class Adapter(requests.adapters.HTTPAdapter):
            def __init__(self):
                super().__init__()
                self.attempts = 0
                self.response = None

            def send(self, request, **kwargs):
                self.attempts += 1
                if self.attempts < 3:
                    raise requests.ConnectTimeout("temporary connect timeout")
                self.response = super().send(request, **kwargs)
                return self.response

        session = requests.Session()
        adapter = Adapter()
        session.mount("http://", adapter)
        self.addCleanup(session.close)
        downloader = self.downloader(session=session)
        with self.assertRaisesRegex(RejectedImage, "Content-Type"):
            downloader.download(self.candidate(self.route(headers={"Content-Type": "text/html"})))
        self.assertEqual(adapter.attempts, 3)
        self.assertEqual(self.hits["/image"], 1)
        self.assertTrue(adapter.response.raw.closed)

    def test_injected_session_remains_usable_after_downloader_close(self):
        session = requests.Session()
        self.addCleanup(session.close)
        downloader = self.downloader(session=session)
        downloader.close()
        # Closing a requests.Session alone is still reusable, so inspect real adapter cleanup.
        with patch.object(session, "close", wraps=session.close) as close:
            downloader.close()
            close.assert_not_called()

    def test_owned_session_closed_once(self):
        self.downloader()  # Establish the public contract before patching the factory.
        real_session = requests.Session()
        with patch("image_collector.downloader.requests.Session", return_value=real_session):
            downloader = self.downloader()
        with patch.object(real_session, "close", wraps=real_session.close) as close:
            downloader.close()
            downloader.close()
            self.assertEqual(close.call_count, 1)


if __name__ == "__main__":
    unittest.main()
