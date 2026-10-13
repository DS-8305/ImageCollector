import os
import time
import requests
from image_collector.models import CollectionError, NeedsAttention, Candidate
from .base import BrowserProvider, http_url, thumbnail_url


class SerpApiProvider(BrowserProvider):
    def __init__(self, options, browser=None, stop_event=None, logger=None):
        super().__init__(options, browser, stop_event, logger)
        self.api_key = os.environ.get("SERPAPI_API_KEY", "")
        if not self.api_key:
            raise CollectionError("SERPAPI_API_KEY is required for the Google API backend.")
        self.session = requests.Session()

    def _request(self, params):
        for attempt in range(3):
            if self.remaining() <= 0:
                raise CollectionError("SerpApi keyword deadline expired.")
            try:
                response = self.session.get("https://serpapi.com/search.json", params=params,
                                            timeout=(min(5, self.remaining()), min(15, self.remaining())))
            except requests.RequestException as exc:
                if attempt == 2:
                    # Requests exception strings may contain the API key in the URL.
                    raise CollectionError("SerpApi network request failed after bounded retries.") from None
                self.pause(attempt + 1)
                continue
            self.check_cancelled()
            if response.status_code in (401, 403, 429):
                raise NeedsAttention(f"SerpApi authorization or quota requires attention (HTTP {response.status_code}).")
            if response.status_code >= 500 and attempt < 2:
                self.pause(attempt + 1)
                continue
            if response.status_code != 200:
                raise CollectionError(f"SerpApi returned HTTP {response.status_code}.")
            try:
                return response.json()
            except ValueError:
                raise CollectionError("SerpApi returned invalid JSON.") from None
        raise CollectionError("SerpApi retry limit reached.")

    def pause(self, seconds):
        end = min(time.monotonic() + seconds, self.deadline)
        while self.remaining() > 0 and time.monotonic() < end:
            if self.stop_event is not None:
                self.stop_event.wait(min(.1, end - time.monotonic()))
            else:
                time.sleep(min(.1, max(0, end - time.monotonic())))
        self.check_cancelled()

    def search(self, keyword):
        self.check_cancelled()
        self.deadline = time.monotonic() + self.options.keyword_timeout
        seen = set()
        params = {"engine": "google_images", "q": keyword, "api_key": self.api_key, "hl": "en"}
        if self.options.period:
            params["period_unit"] = {"day": "d", "week": "w", "month": "m", "year": "y"}[self.options.period]
        if self.options.usage_rights:
            params["licenses"] = {"creative-commons": "cl", "commercial": "ol"}[self.options.usage_rights]
        for page in range(min(100, self.options.max_scrolls)):
            if self.remaining() <= 0:
                return
            params["ijn"] = page
            payload = self._request(params)
            if not isinstance(payload, dict):
                raise CollectionError("SerpApi response schema is invalid.")
            if payload.get("error"):
                message = str(payload["error"]).lower()
                if any(x in message for x in ("quota", "account", "api key", "run out", "captcha", "blocked", "rate limit")):
                    raise NeedsAttention("SerpApi account, quota, or verification requires attention.")
                if "hasn't returned any results" in message or "no results" in message:
                    return
                raise CollectionError("SerpApi reported a search error.")
            rows = payload.get("images_results")
            if not isinstance(rows, list):
                raise CollectionError("SerpApi image result schema is missing.")
            before = len(seen)
            for row in rows:
                self.check_cancelled()
                if self.remaining() <= 0:
                    return
                if not isinstance(row, dict):
                    continue
                original = http_url(row.get("original"))
                thumb = thumbnail_url(row.get("thumbnail"))
                identity = original or thumb
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                yield Candidate(thumb, http_url(row.get("link")), str(row.get("title") or ""),
                                str(row.get("source") or ""), original, "google", len(seen),
                                http_url(row.get("license_details_url")))
                if len(seen) >= self.options.max_candidates:
                    return
            if not rows or len(seen) == before:
                return
            if not payload.get("serpapi_pagination", {}).get("next"):
                return

    def close(self):
        self.session.close()
