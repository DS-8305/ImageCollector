import importlib
import unittest


class ProfileTests(unittest.TestCase):
    def models(self):
        try:
            return importlib.import_module("image_collector.models")
        except ImportError as exc:
            self.fail(f"Collection contracts are missing: {exc}")

    def test_google_defaults_enforce_production_resolution(self):
        m = self.models()
        options = m.CollectionOptions(engine="google").resolve()
        self.assertEqual((options.download_mode, options.profile), ("original-only", "blog"))
        self.assertFalse(options.accepts_size(1199, 800))
        self.assertTrue(options.accepts_size(1200, 800))
        self.assertFalse(options.accepts_size(1200, 149))

    def test_legacy_naver_defaults_preserved(self):
        options = self.models().CollectionOptions().resolve()
        self.assertEqual((options.download_mode, options.min_width, options.min_long_edge), ("thumbnail", 150, 0))
        self.assertTrue(options.headless)

    def test_video_orientation_and_custom_thresholds(self):
        m = self.models()
        horizontal = m.CollectionOptions(engine="google", profile="video-landscape").resolve()
        vertical = m.CollectionOptions(engine="google", profile="video-portrait").resolve()
        self.assertTrue(horizontal.accepts_size(1920, 1080))
        self.assertFalse(horizontal.accepts_size(1080, 1920))
        self.assertTrue(vertical.accepts_size(1080, 1920))
        self.assertFalse(vertical.accepts_size(1920, 1080))
        custom = m.CollectionOptions(engine="google", min_long_edge=800).resolve()
        self.assertEqual(custom.profile, "custom")
        self.assertTrue(custom.accepts_size(800, 600))

    def test_thumbnail_override_and_both_engine_defaults(self):
        m = self.models()
        self.assertEqual(m.CollectionOptions(engine="google", download_mode="thumbnail").resolve().min_long_edge, 0)
        options = m.CollectionOptions(engine="both")
        self.assertEqual(options.resolve("naver").download_mode, "thumbnail")
        self.assertEqual(options.resolve("google").download_mode, "original-only")

    def test_invalid_options_rejected_before_collection(self):
        m = self.models()
        for kwargs in [{"limit": 0}, {"engine": "other"}, {"min_width": 0},
                       {"download_mode": "bogus"}, {"keyword_timeout": 0},
                       {"engine": "naver", "download_mode": "original-only"}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                m.CollectionOptions(**kwargs).resolve()
