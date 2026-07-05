import csv
import json
import unittest
import uuid
from pathlib import Path

from naver_image_collector import (
    BatchResult,
    ImageRecord,
    build_parser,
    clear_generated_images,
    ensure_keyword_folder,
    load_keywords,
    run_batch_collection,
    safe_folder_name,
    write_metadata,
)


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
        self.assertEqual(safe_folder_name("수면안대 암막/숙면"), "수면안대_암막_숙면")
        self.assertEqual(len(safe_folder_name("!!!")), 10)

    def test_ensure_keyword_folder_creates_safe_folder(self):
        root = self._tmp_dir()
        folder = ensure_keyword_folder(root, "수면안대 암막/숙면")
        self.assertTrue(folder.is_dir())
        self.assertEqual(folder.name, "수면안대_암막_숙면")

    def test_write_metadata_creates_csv_and_json(self):
        root = self._tmp_dir()
        records = [
            ImageRecord(
                keyword="수면안대",
                index=1,
                file_name="image_01.jpg",
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
        self.assertEqual(rows[0]["keyword"], "수면안대")
        with json_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        self.assertEqual(data[0]["file_name"], "image_01.jpg")

class BatchInputTests(unittest.TestCase):
    def _tmp_dir(self) -> Path:
        path = Path(__file__).parent / f"_tmp_{uuid.uuid4().hex}"
        path.mkdir()
        self.addCleanup(lambda: HelperTests._remove_tree(self, path))
        return path

    def test_load_keywords_from_csv_skips_blank_rows_and_deduplicates(self):
        root = self._tmp_dir()
        csv_path = root / "keywords.csv"
        csv_path.write_text("keyword\n수면안대\n\n수면안대\n핸드크림\n", encoding="utf-8-sig")

        keywords = load_keywords(csv_path)

        self.assertEqual(keywords, ["수면안대", "핸드크림"])

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
            return [Path("image_01.jpg")]

        results = run_batch_collection(
            ["good", "bad", "next"],
            limit=20,
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
    def test_parser_defaults_to_limit_20(self):
        parser = build_parser()
        args = parser.parse_args(["--keyword", "수면안대"])
        self.assertEqual(args.limit, 20)
        self.assertEqual(args.output_dir, "downloaded_images")


if __name__ == "__main__":
    unittest.main()
