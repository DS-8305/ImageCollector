import csv
import json
import unittest
import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from naver_image_collector import (
    BatchResult,
    ImageRecord,
    NaverImageCollector,
    NaverImageCollectorGUI,
    build_parser,
    clear_generated_images,
    ensure_keyword_folder,
    load_keywords,
    run_batch_collection,
    safe_folder_name,
    write_metadata,
)


KOREAN_KEYWORD = "\uc218\uba74\uc548\ub300"
KOREAN_SAFE_INPUT = "\uc218\uba74\uc548\ub300 \uc554\ub9c9/\uc219\uba74"
KOREAN_SAFE_OUTPUT = "\uc218\uba74\uc548\ub300_\uc554\ub9c9_\uc219\uba74"
KOREAN_OTHER = "\ud578\ub4dc\ud06c\ub9bc"


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class HelperTests(unittest.TestCase):
    def _tmp_dir(self) -> Path:
        path = Path(__file__).parent / f"_tmp_{uuid.uuid4().hex}"
        path.mkdir()
        self.addCleanup(lambda: self._remove_tree(path))
        return path

    def _remove_tree(self, path: Path) -> None:
        if not path.exists():
            return
        for child in path.iterdir():
            if child.is_dir():
                self._remove_tree(child)
            else:
                child.unlink()
        path.rmdir()

    def test_safe_folder_name_preserves_korean_and_replaces_punctuation(self):
        self.assertEqual(safe_folder_name(KOREAN_SAFE_INPUT), KOREAN_SAFE_OUTPUT)
        self.assertEqual(len(safe_folder_name("!!!")), 10)

    def test_ensure_keyword_folder_creates_safe_folder(self):
        root = self._tmp_dir()
        folder = ensure_keyword_folder(root, KOREAN_SAFE_INPUT)
        self.assertTrue(folder.is_dir())
        self.assertEqual(folder.name, KOREAN_SAFE_OUTPUT)

    def test_write_metadata_creates_csv_and_json(self):
        root = self._tmp_dir()
        records = [
            ImageRecord(
                keyword=KOREAN_KEYWORD,
                index=1,
                file_name="image_01.png",
                thumbnail_url="https://example.com/thumb.jpg",
                source_url="https://example.com/source",
                title="title",
                source="source",
                status="saved",
                error="",
            )
        ]

        write_metadata(root, records)

        csv_path = root / "metadata.csv"
        json_path = root / "metadata.json"
        self.assertTrue(csv_path.is_file())
        self.assertTrue(json_path.is_file())
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(rows[0]["keyword"], KOREAN_KEYWORD)
        with json_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        self.assertEqual(data[0]["file_name"], "image_01.png")


class BatchInputTests(unittest.TestCase):
    def _tmp_dir(self) -> Path:
        path = Path(__file__).parent / f"_tmp_{uuid.uuid4().hex}"
        path.mkdir()
        self.addCleanup(lambda: HelperTests._remove_tree(self, path))
        return path

    def test_load_keywords_from_csv_skips_blank_rows_and_deduplicates(self):
        root = self._tmp_dir()
        csv_path = root / "keywords.csv"
        csv_path.write_text(
            f"keyword\n{KOREAN_KEYWORD}\n\n{KOREAN_KEYWORD}\n{KOREAN_OTHER}\n",
            encoding="utf-8-sig",
        )

        keywords = load_keywords(csv_path)

        self.assertEqual(keywords, [KOREAN_KEYWORD, KOREAN_OTHER])

    def test_load_keywords_from_csv_accepts_header_variants_and_preserves_order(self):
        root = self._tmp_dir()
        csv_path = root / "keywords.csv"
        csv_path.write_text(
            f" Keyword \n  {KOREAN_KEYWORD}  \n\n{KOREAN_OTHER}\n{KOREAN_KEYWORD}\n",
            encoding="utf-8-sig",
        )

        keywords = load_keywords(csv_path)

        self.assertEqual(keywords, [KOREAN_KEYWORD, KOREAN_OTHER])

    def test_load_keywords_from_csv_requires_keyword_in_first_column(self):
        root = self._tmp_dir()
        csv_path = root / "keywords.csv"
        csv_path.write_text(
            f"name,keyword\nexample,{KOREAN_KEYWORD}\n",
            encoding="utf-8-sig",
        )

        with self.assertRaisesRegex(ValueError, "first CSV header must be keyword"):
            load_keywords(csv_path)

    def test_load_keywords_from_csv_rejects_missing_keyword_header(self):
        root = self._tmp_dir()
        csv_path = root / "keywords.csv"
        csv_path.write_text(f"name\n{KOREAN_KEYWORD}\n", encoding="utf-8-sig")

        with self.assertRaisesRegex(ValueError, "first CSV header must be keyword"):
            load_keywords(csv_path)

    def test_load_keywords_from_csv_rejects_file_without_valid_terms(self):
        root = self._tmp_dir()
        csv_path = root / "keywords.csv"
        csv_path.write_text("keyword\n\n", encoding="utf-8-sig")

        with self.assertRaisesRegex(ValueError, "No non-empty keyword rows"):
            load_keywords(csv_path)

    def test_clear_generated_images_removes_old_image_files_only(self):
        root = self._tmp_dir()
        (root / "image_01.jpg").write_bytes(b"old")
        (root / "image_02.png").write_bytes(b"old")
        (root / "metadata.csv").write_text("keep", encoding="utf-8")

        clear_generated_images(root)

        self.assertFalse((root / "image_01.jpg").exists())
        self.assertFalse((root / "image_02.png").exists())
        self.assertTrue((root / "metadata.csv").exists())


class BatchRunnerTests(unittest.TestCase):
    def test_run_batch_collection_continues_after_failure(self):
        calls = []

        def fake_collect(keyword: str, limit: int, output_root: Path, headless: bool, min_thumbnail_size: int):
            calls.append(keyword)
            self.assertEqual(min_thumbnail_size, 150)
            if keyword == "bad":
                raise RuntimeError("boom")
            return [Path("image_01.png")]

        results = run_batch_collection(
            ["good", "bad", "next"],
            limit=50,
            output_root=Path("downloaded_images"),
            headless=True,
            logger=lambda _message: None,
            collector_func=fake_collect,
        )

        self.assertEqual(calls, ["good", "bad", "next"])
        self.assertEqual(
            results,
            [
                BatchResult(keyword="good", saved_count=1, status="success", error=""),
                BatchResult(keyword="bad", saved_count=0, status="failed", error="boom"),
                BatchResult(keyword="next", saved_count=1, status="success", error=""),
            ],
        )


class GuiBatchUploadTests(unittest.TestCase):
    def _tmp_dir(self) -> Path:
        path = Path(__file__).parent / f"_tmp_{uuid.uuid4().hex}"
        path.mkdir()
        self.addCleanup(lambda: HelperTests._remove_tree(self, path))
        return path

    def test_validate_batch_file_caches_keywords_and_logs_preview(self):
        root = self._tmp_dir()
        csv_path = root / "keywords.csv"
        csv_path.write_text(
            f"keyword\n{KOREAN_KEYWORD}\n{KOREAN_OTHER}\n",
            encoding="utf-8-sig",
        )
        gui = NaverImageCollectorGUI.__new__(NaverImageCollectorGUI)
        gui.batch_file_var = FakeVar("")
        gui.batch_keywords = []
        gui.validated_batch_file = ""
        messages = []
        gui._append_log = messages.append

        keywords = gui._validate_batch_file(str(csv_path))

        self.assertEqual(keywords, [KOREAN_KEYWORD, KOREAN_OTHER])
        self.assertEqual(gui.batch_file_var.get(), str(csv_path))
        self.assertEqual(gui.batch_keywords, keywords)
        self.assertEqual(gui.validated_batch_file, str(csv_path))
        self.assertIn("2", messages[-1])
        self.assertIn(KOREAN_KEYWORD, messages[-1])

    def test_start_batch_run_passes_cached_keywords_to_background_task(self):
        gui = NaverImageCollectorGUI.__new__(NaverImageCollectorGUI)
        gui.batch_file_var = FakeVar("keywords.csv")
        gui.batch_keywords = [KOREAN_KEYWORD, KOREAN_OTHER]
        gui.validated_batch_file = "keywords.csv"
        gui.limit_var = FakeVar("50")
        gui.min_thumbnail_size_var = FakeVar("150")
        calls = []
        gui._run_in_thread = lambda target, *args: calls.append((target, args))

        gui._start_batch_run()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1][0], [KOREAN_KEYWORD, KOREAN_OTHER])
        self.assertEqual(calls[0][1][1:], (50, 150))

    def test_choose_batch_file_logs_validation_failure_and_does_not_start_search(self):
        root = self._tmp_dir()
        csv_path = root / "invalid.csv"
        csv_path.write_text(f"name\n{KOREAN_KEYWORD}\n", encoding="utf-8-sig")
        gui = NaverImageCollectorGUI.__new__(NaverImageCollectorGUI)
        gui.batch_file_var = FakeVar("")
        gui.batch_keywords = []
        gui.validated_batch_file = ""
        messages = []
        gui._append_log = messages.append
        run_calls = []
        gui._run_in_thread = lambda target, *args: run_calls.append((target, args))

        with (
            patch("tkinter.filedialog.askopenfilename", return_value=str(csv_path)),
            patch("tkinter.messagebox.showerror") as showerror,
        ):
            gui._choose_batch_file()

        self.assertEqual(run_calls, [])
        self.assertIn("Batch file validation failed", messages[-1])
        showerror.assert_called_once()

    def test_start_batch_run_logs_failure_when_edited_path_is_invalid(self):
        root = self._tmp_dir()
        csv_path = root / "invalid.csv"
        csv_path.write_text(f"name\n{KOREAN_KEYWORD}\n", encoding="utf-8-sig")
        gui = NaverImageCollectorGUI.__new__(NaverImageCollectorGUI)
        gui.batch_file_var = FakeVar(str(csv_path))
        gui.batch_keywords = [KOREAN_OTHER]
        gui.validated_batch_file = "old.csv"
        gui.limit_var = FakeVar("50")
        gui.min_thumbnail_size_var = FakeVar("150")
        messages = []
        gui._append_log = messages.append
        calls = []
        gui._run_in_thread = lambda target, *args: calls.append((target, args))

        with patch("tkinter.messagebox.showerror") as showerror:
            gui._start_batch_run()

        self.assertEqual(calls, [])
        self.assertIn("Batch file validation failed", messages[-1])
        showerror.assert_called_once()


class CliTests(unittest.TestCase):
    def test_parser_defaults_to_limit_50(self):
        parser = build_parser()
        args = parser.parse_args(["--keyword", KOREAN_KEYWORD])
        self.assertEqual(args.limit, 50)
        self.assertEqual(args.output_dir, "downloaded_images")


class SearchUrlTests(unittest.TestCase):
    def test_search_url_requests_latest_sort(self):
        collector = NaverImageCollector.__new__(NaverImageCollector)

        url = collector._search_url("keyword")

        self.assertIn("where=image", url)
        self.assertIn("sort=date", url)
        self.assertIn("query=keyword", url)


class DownloadFilterTests(unittest.TestCase):
    def _tmp_dir(self) -> Path:
        path = Path(__file__).parent / f"_tmp_{uuid.uuid4().hex}"
        path.mkdir()
        self.addCleanup(lambda: HelperTests._remove_tree(self, path))
        return path

    def _png_bytes(self, size: tuple[int, int]) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", size, color="red").save(buffer, "PNG")
        return buffer.getvalue()

    def test_download_thumbnail_rejects_images_below_minimum_size(self):
        class Response:
            content = self._png_bytes((120, 180))

            def raise_for_status(self):
                return None

        class Session:
            def get(self, _url, timeout):
                return Response()

        root = self._tmp_dir()
        collector = NaverImageCollector.__new__(NaverImageCollector)
        collector.session = Session()
        collector.min_thumbnail_size = 150

        with self.assertRaisesRegex(ValueError, "smaller than minimum"):
            collector._download_thumbnail("https://example.com/small.png", root / "image_01.png")

        self.assertFalse((root / "image_01.png").exists())

    def test_download_thumbnail_saves_images_at_minimum_size(self):
        class Response:
            content = self._png_bytes((150, 150))

            def raise_for_status(self):
                return None

        class Session:
            def get(self, _url, timeout):
                return Response()

        root = self._tmp_dir()
        collector = NaverImageCollector.__new__(NaverImageCollector)
        collector.session = Session()
        collector.min_thumbnail_size = 150

        collector._download_thumbnail("https://example.com/ok.png", root / "image_01.png")

        with Image.open(root / "image_01.png") as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (150, 150))


class ThumbnailSizeCliTests(unittest.TestCase):
    def test_parser_defaults_to_mobile_thumbnail_minimum(self):
        parser = build_parser()
        args = parser.parse_args(["--keyword", KOREAN_KEYWORD])

        self.assertEqual(args.min_thumbnail_size, 150)


if __name__ == "__main__":
    unittest.main()
