import csv
import json
import unittest
import uuid
from pathlib import Path

from naver_image_collector import (
    BatchResult,
    ImageRecord,
    NaverImageCollector,
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

        def fake_collect(keyword: str, limit: int, output_root: Path, headless: bool):
            calls.append(keyword)
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


if __name__ == "__main__":
    unittest.main()
