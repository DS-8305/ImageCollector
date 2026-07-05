# Naver Image Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Tkinter-first Python app that searches Naver Image Search, downloads thumbnail images, and writes CSV/JSON metadata with original/source URLs.

**Architecture:** Implement a compact single-file app for the first version because the project is new and the reference app follows this pattern. Keep the core collector, CSV/XLSX loader, metadata writer, CLI, and GUI as separate functions/classes inside `naver_image_collector.py` with testable pure helpers. Use Selenium for live search and `requests` for thumbnail downloads.

**Tech Stack:** Python 3.10+, Selenium, webdriver-manager, requests, Pillow, openpyxl, Tkinter, unittest.

---

## File Structure

- Create `naver_image_collector.py`: dataclasses, safe filename helper, CSV/XLSX loading, Naver Selenium collector, metadata writer, batch runner, CLI, and Tkinter GUI.
- Create `requirements.txt`: runtime dependencies.
- Create `README.md`: installation, GUI usage, CLI usage, CSV input, output structure.
- Create `sample_keywords.csv`: example input with `keyword`.
- Create `tests/__init__.py`: test package marker.
- Create `tests/test_naver_image_collector.py`: network-free unit tests.

## Task 1: Pure Helpers and Metadata Tests

**Files:**
- Create: `tests/test_naver_image_collector.py`
- Create: `tests/__init__.py`
- Create: `naver_image_collector.py`

- [ ] **Step 1: Write failing tests for safe filenames and metadata writing**

```python
import csv
import json
import unittest
import uuid
from pathlib import Path

from naver_image_collector import ImageRecord, ensure_keyword_folder, safe_folder_name, write_metadata


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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_naver_image_collector -v`
Expected: FAIL with import errors because `naver_image_collector.py` does not exist.

- [ ] **Step 3: Implement minimal helpers and metadata writer**

```python
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


METADATA_FIELDS = [
    "keyword",
    "index",
    "file_name",
    "thumbnail_url",
    "source_url",
    "title",
    "source",
    "status",
    "error",
]


@dataclass(slots=True)
class ImageRecord:
    keyword: str
    index: int
    file_name: str
    thumbnail_url: str
    source_url: str
    title: str
    source: str
    status: str
    error: str


def safe_folder_name(value: str) -> str:
    safe_value = re.sub(r"[^\w\-]+", "_", value.strip(), flags=re.UNICODE)
    safe_value = safe_value.strip("_")
    if safe_value:
        return safe_value[:120]
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def ensure_keyword_folder(output_root: str | Path, keyword: str) -> Path:
    folder_path = Path(output_root) / safe_folder_name(keyword)
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path


def write_metadata(folder_path: str | Path, records: list[ImageRecord]) -> None:
    folder = Path(folder_path)
    folder.mkdir(parents=True, exist_ok=True)
    rows = [asdict(record) for record in records]
    with (folder / "metadata.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=METADATA_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with (folder / "metadata.json").open("w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_naver_image_collector -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add naver_image_collector.py tests/__init__.py tests/test_naver_image_collector.py
git commit -m "Add image metadata helpers"
```

## Task 2: CSV/XLSX Loading and Generated Image Cleanup

**Files:**
- Modify: `tests/test_naver_image_collector.py`
- Modify: `naver_image_collector.py`

- [ ] **Step 1: Add failing tests for batch loading and cleanup**

```python
from naver_image_collector import clear_generated_images, load_keywords


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_naver_image_collector -v`
Expected: FAIL because `load_keywords` and `clear_generated_images` are not defined.

- [ ] **Step 3: Implement CSV/XLSX loading and cleanup**

```python
try:
    from openpyxl import load_workbook
except ImportError:
    load_workbook = None


IMAGE_FILE_PATTERN = re.compile(r"^image_\d+\.(jpg|jpeg|png|webp)$", re.IGNORECASE)


def clear_generated_images(folder_path: str | Path) -> None:
    folder = Path(folder_path)
    if not folder.exists():
        return
    for child in folder.iterdir():
        if child.is_file() and IMAGE_FILE_PATTERN.match(child.name):
            child.unlink()


def load_keywords(file_path: str | Path) -> list[str]:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _load_keywords_from_csv(path)
    if suffix == ".xlsx":
        return _load_keywords_from_xlsx(path)
    raise ValueError("Only .csv and .xlsx files are supported.")


def _dedupe_keywords(values: list[str]) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for value in values:
        keyword = value.strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)
    if not keywords:
        raise ValueError("No non-empty keyword rows were found.")
    return keywords


def _load_keywords_from_csv(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        headers = {header.strip().lower(): header for header in (reader.fieldnames or []) if header}
        if "keyword" not in headers:
            raise ValueError("CSV header must include keyword.")
        keyword_header = headers["keyword"]
        return _dedupe_keywords([(row.get(keyword_header) or "") for row in reader])


def _load_keywords_from_xlsx(path: Path) -> list[str]:
    if load_workbook is None:
        raise RuntimeError("openpyxl is required for XLSX files.")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        rows = list(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    if not rows:
        raise ValueError("XLSX file is empty.")
    headers = [str(cell).strip().lower() if cell is not None else "" for cell in rows[0]]
    try:
        keyword_index = headers.index("keyword")
    except ValueError as exc:
        raise ValueError("XLSX header must include keyword.") from exc
    return _dedupe_keywords([
        str(row[keyword_index]) if keyword_index < len(row) and row[keyword_index] is not None else ""
        for row in rows[1:]
    ])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_naver_image_collector -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add naver_image_collector.py tests/test_naver_image_collector.py
git commit -m "Add keyword batch loading"
```

## Task 3: Selenium Collector and Batch Runner

**Files:**
- Modify: `naver_image_collector.py`
- Modify: `tests/test_naver_image_collector.py`

- [ ] **Step 1: Add failing test for batch continuation**

```python
from naver_image_collector import BatchResult, run_batch_collection


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
            collector_func=fake_collect,
        )

        self.assertEqual(calls, ["good", "bad", "next"])
        self.assertEqual(results, [
            BatchResult(keyword="good", saved_count=1, status="success", error=""),
            BatchResult(keyword="bad", saved_count=0, status="failed", error="boom"),
            BatchResult(keyword="next", saved_count=1, status="success", error=""),
        ])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_naver_image_collector -v`
Expected: FAIL because `BatchResult` and `run_batch_collection` are not defined.

- [ ] **Step 3: Implement collector, thumbnail download, and batch runner**

Implement:

- `ImageCandidate` dataclass with `thumbnail_url`, `source_url`, `title`, `source`.
- `BatchResult` dataclass.
- `NaverImageCollector` with Selenium browser setup, search URL creation, scrolling, candidate extraction via JavaScript, thumbnail download, and `collect_keyword`.
- `collect_single_keyword` wrapper that closes the browser.
- `run_batch_collection` that continues after failures.

The Selenium extraction should query images from Naver search result containers and use defensive fallbacks:

```python
items = self.driver.execute_script(
    """
    const results = [];
    const images = Array.from(document.querySelectorAll('img'));
    for (const img of images) {
      const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';
      if (!src || src.startsWith('data:')) continue;
      const box = img.getBoundingClientRect();
      if (box.width < 80 || box.height < 80) continue;
      const anchor = img.closest('a');
      const container = img.closest('div, li, section') || img.parentElement;
      const text = container ? container.innerText : '';
      results.push({
        thumbnailUrl: src,
        sourceUrl: anchor ? anchor.href : '',
        title: img.alt || img.title || '',
        source: text.split('\\n').slice(0, 2).join(' / '),
        width: Math.round(box.width),
        height: Math.round(box.height)
      });
    }
    return results;
    """
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_naver_image_collector -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add naver_image_collector.py tests/test_naver_image_collector.py
git commit -m "Add Naver image collection engine"
```

## Task 4: CLI, GUI, Docs, and Manual Verification

**Files:**
- Modify: `naver_image_collector.py`
- Create: `requirements.txt`
- Create: `README.md`
- Create: `sample_keywords.csv`

- [ ] **Step 1: Add CLI default test**

```python
from naver_image_collector import build_parser


class CliTests(unittest.TestCase):
    def test_parser_defaults_to_limit_20(self):
        parser = build_parser()
        args = parser.parse_args(["--keyword", "수면안대"])
        self.assertEqual(args.limit, 20)
        self.assertEqual(args.output_dir, "downloaded_images")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_naver_image_collector -v`
Expected: FAIL because `build_parser` is not defined.

- [ ] **Step 3: Implement CLI and Tkinter GUI**

Implement:

- `build_parser` with `--keyword`, `--batch-file`, `--limit`, `--output-dir`, `--show-browser`, `--gui`.
- `main` that opens GUI when no arguments are provided.
- `NaverImageCollectorGUI` with single search, CSV batch, output folder picker, visible browser checkbox, run buttons, and log text.
- Background threads for collection.

- [ ] **Step 4: Add docs and sample CSV**

Create:

```text
requirements.txt
selenium>=4.22.0
webdriver-manager>=4.0.2
requests>=2.32.0
Pillow>=10.4.0
openpyxl>=3.1.5
```

Create `sample_keywords.csv`:

```csv
keyword
수면안대
핸드크림
```

Create README with install, GUI, CLI, CSV, and output examples.

- [ ] **Step 5: Run automated tests**

Run: `python -m unittest discover -v`
Expected: PASS.

- [ ] **Step 6: Run live CLI smoke test**

Run: `python .\naver_image_collector.py --keyword "수면안대" --limit 3 --output-dir .\_smoke_output`
Expected: Creates `_smoke_output/수면안대/`, saves up to 3 `image_*.jpg` files, plus metadata files.

- [ ] **Step 7: Commit**

```bash
git add naver_image_collector.py requirements.txt README.md sample_keywords.csv tests/test_naver_image_collector.py
git commit -m "Add Naver image collector app"
```

## Self-Review

- Spec coverage: GUI default execution, CLI single, CLI batch, CSV/XLSX loading, thumbnail download, metadata CSV/JSON, output folder control, and network-free tests are covered.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: `ImageRecord`, `BatchResult`, `load_keywords`, `write_metadata`, `run_batch_collection`, and `build_parser` names are consistent across tasks.
