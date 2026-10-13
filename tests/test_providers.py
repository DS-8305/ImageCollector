"""Provider behavior tests; external browsers/HTTP are replaced at their boundary."""
import importlib
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from image_collector.models import CollectionOptions, Cancelled, CollectionError, NeedsAttention


class ProviderTests(unittest.TestCase):
    def module(self, name):
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            self.fail(f"Provider implementation missing: {exc}")

    def test_browser_is_lazy_reuses_driver_and_closes_once(self):
        module = self.module("image_collector.browser")
        with patch.object(module.BrowserSession, "_create_driver") as create:
            browser = module.BrowserSession(headless=True)
            self.assertFalse(create.called)
            first = browser.driver
            self.assertIs(browser.driver, first)
            self.assertEqual(create.call_count, 1)
            browser.close()
            browser.close()
            first.quit.assert_called_once()

    def test_google_filters_are_sent_as_actual_search_parameters(self):
        from urllib.parse import urlparse, parse_qs
        module = self.module("image_collector.providers.google")
        options = CollectionOptions(engine="google", period="week", usage_rights="creative-commons").resolve()
        provider = module.GoogleProvider(options, object())
        params = parse_qs(urlparse(provider.search_url("red apple")).query)
        self.assertEqual(params["q"], ["red apple"])
        self.assertEqual(params["udm"], ["2"])
        self.assertEqual(params["tbs"], ["qdr:w,sur:cl"])

    def test_factory_rejects_api_without_key_and_unsupported_engine(self):
        module = self.module("image_collector.providers")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(CollectionError):
                module.create_provider("google", CollectionOptions(engine="google", backend="api").resolve(), object())
        with self.assertRaises(ValueError):
            module.create_provider("other", CollectionOptions().resolve(), object())

    def test_google_period_and_commercial_filter(self):
        module = self.module("image_collector.providers.google")
        provider = module.GoogleProvider(CollectionOptions(engine="google", period="year", usage_rights="commercial").resolve(), object())
        self.assertIn("qdr%3Ay%2Csur%3Aol", provider.search_url("cat"))

    def test_api_filters_use_documented_dedicated_parameters(self):
        module = self.module("image_collector.providers.api")
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            provider = module.SerpApiProvider(CollectionOptions(engine="google", backend="api", period="month", usage_rights="commercial").resolve())
        with patch.object(provider, "_request", return_value={"images_results": []}) as request:
            self.assertEqual(list(provider.search("apple")), [])
        params = request.call_args.args[0]
        self.assertEqual(params.get("period_unit"), "m")
        self.assertEqual(params.get("licenses"), "ol")

    def test_api_request_honors_cancellation_after_response(self):
        import time
        module = self.module("image_collector.providers.api")
        event = threading.Event()
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            provider = module.SerpApiProvider(CollectionOptions(engine="google", backend="api").resolve(), stop_event=event)
        provider.deadline = time.monotonic() + 2
        def response(*args, **kwargs):
            event.set()
            return SimpleNamespace(status_code=200, json=lambda: {"images_results": []})
        with patch.object(provider.session, "get", side_effect=response):
            with self.assertRaises(Cancelled):
                provider._request({"engine": "google_images"})

    def test_api_keeps_original_source_thumbnail_and_license_distinct(self):
        module = self.module("image_collector.providers.api")
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            provider = module.SerpApiProvider(CollectionOptions(engine="google", backend="api", max_candidates=1).resolve())
        self.assertTrue(callable(getattr(provider, "search", None)), "API search is not implemented")
        with patch.object(provider, "_request", return_value={"images_results": [
            {"original": "https://images.example/full.jpg", "thumbnail": "https://thumb.example/a.jpg",
             "link": "https://site.example/page", "title": "Apple", "source": "Example",
             "license_details_url": "https://site.example/license"}]}):
            result = list(provider.search("apple"))
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0].original_url, result[0].source_url, result[0].thumbnail_url,
                          result[0].license_url), ("https://images.example/full.jpg", "https://site.example/page",
                                                 "https://thumb.example/a.jpg", "https://site.example/license"))

    def test_api_blocked_error_is_attention_and_missing_result_schema_is_failure(self):
        module = self.module("image_collector.providers.api")
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            provider = module.SerpApiProvider(CollectionOptions(engine="google", backend="api").resolve())
        self.assertTrue(callable(getattr(provider, "search", None)), "API search is not implemented")
        for payload, error in [({"error": "Your account has run out of searches"}, NeedsAttention),
                               ({"unexpected_schema": []}, CollectionError)]:
            with self.subTest(payload=payload), patch.object(provider, "_request", return_value=payload):
                with self.assertRaises(error):
                    list(provider.search("apple"))

    def test_cancelled_api_does_not_make_a_request(self):
        module = self.module("image_collector.providers.api")
        event = threading.Event()
        event.set()
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            provider = module.SerpApiProvider(CollectionOptions(engine="google", backend="api").resolve(), stop_event=event)
        self.assertTrue(callable(getattr(provider, "search", None)), "API search is not implemented")
        with patch.object(provider, "_request") as request:
            with self.assertRaises(Cancelled):
                list(provider.search("apple"))
            request.assert_not_called()

    def test_api_transport_retries_only_three_times_and_never_exposes_key(self):
        import requests
        module = self.module("image_collector.providers.api")
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "do-not-expose"}):
            provider = module.SerpApiProvider(CollectionOptions(engine="google", backend="api").resolve())
        with patch.object(provider.session, "get", side_effect=requests.ConnectionError("api_key=do-not-expose")) as request, patch.object(provider, "pause"):
            with self.assertRaises(CollectionError) as caught:
                list(provider.search("apple"))
        self.assertEqual(request.call_count, 3)
        self.assertNotIn("do-not-expose", str(caught.exception))

    def test_api_pagination_is_bounded_and_duplicate_pages_stop(self):
        module = self.module("image_collector.providers.api")
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            provider = module.SerpApiProvider(CollectionOptions(engine="google", backend="api", max_scrolls=2).resolve())
        pages=[]
        def transport(params):
            page=params["ijn"]
            pages.append(page)
            return {"images_results": [{"original": f"https://images.example/{page}.jpg", "thumbnail": f"https://thumb.example/{page}.jpg"}],
                    "serpapi_pagination": {"next": "https://serpapi.com/search.json?ijn=next"}}
        with patch.object(provider, "_request", side_effect=transport):
            result=list(provider.search("apple"))
        self.assertEqual(pages, [0, 1])
        self.assertEqual([x.original_url for x in result], ["https://images.example/0.jpg", "https://images.example/1.jpg"])
        repeated={"images_results": [{"original": "https://images.example/repeat.jpg", "thumbnail": "https://thumb.example/repeat.jpg"}],
                  "serpapi_pagination": {"next": "https://serpapi.com/search.json?ijn=next"}}
        with patch.object(provider, "_request", return_value=repeated) as request:
            self.assertEqual(len(list(provider.search("apple"))), 1)
        self.assertEqual(request.call_count, 2)

    def test_api_quota_status_requires_attention_without_retry(self):
        module = self.module("image_collector.providers.api")
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test-key"}):
            provider = module.SerpApiProvider(CollectionOptions(engine="google", backend="api").resolve())
        with patch.object(provider.session, "get", return_value=SimpleNamespace(status_code=429)) as request:
            with self.assertRaises(NeedsAttention):
                list(provider.search("apple"))
        self.assertEqual(request.call_count, 1)


class DOMProviderTests(unittest.TestCase):
    """Exercise selectors, click transitions, and waits in a real local Chrome."""
    @classmethod
    def setUpClass(cls):
        from image_collector.browser import BrowserSession
        cls.session = BrowserSession(headless=True)
        cls.driver = cls.session.driver
        cls.driver.execute_cdp_cmd("Network.enable", {})
        cls.driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": ["https://*", "http://*"]})

    @classmethod
    def tearDownClass(cls):
        cls.session.close()

    def provider(self, fixture, engine="google", **options):
        from image_collector.providers import create_provider
        target = (Path(__file__).parent / "fixtures" / fixture).resolve().as_uri()
        real = self.driver

        class FixtureDriver:
            def get(self, _url):
                real.get(target)

            def __getattr__(self, name):
                return getattr(real, name)

        resolved = CollectionOptions(engine=engine, max_scrolls=1, keyword_timeout=2, **options).resolve()
        provider = create_provider(engine, resolved, SimpleNamespace(driver=FixtureDriver()))
        self.assertTrue(callable(getattr(provider, "search", None)), "Browser search is not implemented")
        return provider

    def test_google_cards_exclude_logo_and_keep_data_thumbnail_without_click(self):
        provider = self.provider("provider_google.html", download_mode="thumbnail", max_candidates=1)
        result = list(provider.search("apple"))
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].thumbnail_url.startswith("data:image/png;base64,"))
        self.assertEqual(result[0].title, "First apple")
        self.assertEqual(result[0].original_url, "")
        self.assertEqual(self.driver.execute_script("return window.clicks"), 0)

    def test_google_waits_for_each_detail_change_and_keeps_source_distinct(self):
        provider = self.provider("provider_google.html", max_candidates=2)
        result = list(provider.search("apple"))
        self.assertEqual([x.original_url for x in result], ["https://images.example/first.jpg", "https://images.example/second.jpg"])
        self.assertEqual([x.source_url for x in result], ["https://source.example/first", "https://source.example/second"])
        self.assertEqual([x.rank for x in result], [1, 2])

    def test_google_modern_detail_keeps_full_image_and_ignores_cached_preview(self):
        result = list(self.provider("provider_google_modern.html", max_candidates=2).search("apple"))
        self.assertEqual([candidate.original_url for candidate in result],
                         ["https://images.example/first.png", "https://images.example/second.png"])
        self.assertEqual([candidate.source_url for candidate in result],
                         ["https://source.example/first", "https://source.example/second"])

    def test_google_modern_detail_downloads_real_originals_and_saves_png(self):
        import json
        import tempfile
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from io import BytesIO
        from PIL import Image
        from image_collector.runner import run_collection
        from image_collector.storage import load_run

        images = {}
        for name, color in (("first", "red"), ("second", "blue")):
            buffer = BytesIO()
            Image.new("RGB", (1200, 800), color).save(buffer, "PNG")
            images[f"/{name}.png"] = buffer.getvalue()

        class ImageHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                body = images.get(self.path)
                self.send_response(200 if body else 404)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                if body:
                    self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), ImageHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
                fixture = Path(root) / "google.html"
                html = (Path(__file__).parent / "fixtures/provider_google_modern.html").read_text(encoding="utf-8")
                fixture.write_text(html.replace("https://images.example", base), encoding="utf-8")
                def supply(engine, options, browser, **kwargs):
                    provider = self.provider(str(fixture))
                    provider.options = options
                    provider.stop_event = kwargs["stop_event"]
                    provider.logger = kwargs["logger"]
                    return provider
                result = run_collection(["a"], CollectionOptions(engine="google", limit=2, max_candidates=2),
                                        output_root=Path(root) / "output", provider_factory=supply)
                self.assertEqual((result.status, result.saved_count), ("success", 2))
                job = next(iter(load_run(result.run_dir)["jobs"].values()))
                metadata = json.loads((result.run_dir / job["folder"] / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual([row["downloaded_url"] for row in metadata], [base+"/first.png", base+"/second.png"])
                self.assertEqual([row["download_kind"] for row in metadata], ["original", "original"])
                for row, color in zip(metadata, ((255, 0, 0, 255), (0, 0, 255, 255))):
                    with Image.open(result.run_dir / job["folder"] / row["file_name"]) as image:
                        self.assertEqual((image.format, image.size), ("PNG", (1200, 800)))
                        self.assertEqual(image.getpixel((0, 0)), color)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_google_stale_detail_is_not_assigned_to_next_card(self):
        provider = self.provider("provider_google_stale.html", max_candidates=2)
        result = list(provider.search("apple"))
        self.assertEqual(result[0].original_url, "https://images.example/first.jpg")
        self.assertEqual(result[1].original_url, "")

    def test_block_consent_empty_and_dom_change_remain_distinct(self):
        for fixture, error in [("provider_blocked.html", NeedsAttention),
                               ("provider_consent.html", NeedsAttention),
                               ("provider_changed.html", CollectionError)]:
            with self.subTest(fixture=fixture), self.assertRaises(error):
                list(self.provider(fixture).search("apple"))
        self.assertEqual(list(self.provider("provider_empty.html").search("apple")), [])

    def test_naver_scoped_thumbnails_preserve_latest_sort(self):
        from urllib.parse import urlparse, parse_qs
        provider = self.provider("provider_naver.html", engine="naver", max_candidates=1)
        self.assertEqual(parse_qs(urlparse(provider.search_url("사과")).query)["sort"], ["date"])
        result = list(provider.search("사과"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].thumbnail_url, "https://thumb.example/naver.jpg")
        self.assertEqual(result[0].engine, "naver")

    def test_naver_observed_initial_result_payload_is_available_before_grid_renders(self):
        result = list(self.provider("provider_naver_live.html", engine="naver", max_candidates=1).search("red apple"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source_url, "https://www.colourbox.com/image/red-apple-image-8383397")
        self.assertTrue(result[0].thumbnail_url.startswith("https://search.pstatic.net/"))
        self.assertEqual(result[0].original_url, "")

    def test_pre_cancelled_browser_search_never_navigates(self):
        provider = self.provider("provider_google.html")
        event = threading.Event()
        event.set()
        provider.stop_event = event
        with patch.object(provider.browser.driver, "get") as navigate:
            with self.assertRaises(Cancelled):
                list(provider.search("apple"))
            navigate.assert_not_called()

    def test_no_results_phrase_inside_a_result_title_is_not_empty(self):
        result = list(self.provider("provider_google_title.html", download_mode="thumbnail", max_candidates=1).search("apple"))
        self.assertEqual(len(result), 1)


    def test_visible_verification_can_be_resolved_in_same_session(self):
        import tempfile
        html = """<html><body><form id="captcha-form">Verification required</form>
        <script>setTimeout(()=>{document.body.innerHTML='<div class="isv-r" data-docid="after"><img src="https://thumb.example/after.png" alt="Resolved result"></div>';},700);</script></body></html>"""
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as root:
            path=Path(root)/"manual-verification.html"
            path.write_text(html,encoding="utf-8")
            provider=self.provider(str(path),download_mode="thumbnail",headless=False,max_candidates=1)
            messages=[]
            provider.logger=messages.append
            try:
                candidates=list(provider.search("apple"))
            except NeedsAttention:
                self.fail("Visible verification was closed instead of waiting for the user")
            self.assertEqual([c.title for c in candidates],["Resolved result"])
            self.assertTrue(any("확인" in message for message in messages))


    def test_captured_google_live_block_is_attention(self):
        with self.assertRaises(NeedsAttention):
            list(self.provider("provider_google_live.html").search("apple"))


if __name__ == "__main__":
    unittest.main()
