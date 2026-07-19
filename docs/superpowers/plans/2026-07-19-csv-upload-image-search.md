# CSV Upload Image Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Tkinter GUI validate an uploaded `keyword` CSV, preview its parsed terms, and search every valid term in order when the user starts the batch.

**Architecture:** Keep the existing `load_keywords()` and `run_batch_collection()` boundaries. Add small GUI methods that cache a validated file path and its parsed keyword list; pass that exact list into the background task so previewed data and executed data match.

**Tech Stack:** Python 3, Tkinter, `csv`, `unittest`; no new dependencies.

## Global Constraints

- The first column header is `keyword`; terms start on row 2.
- Skip empty cells and later duplicates while retaining first-occurrence order.
- File selection validates and previews but never starts browser or network activity.
- Keep single-keyword, CLI, XLSX, output, and metadata behavior compatible.
- Continue later keywords after an individual collection failure.

---

### Task 1: Lock the CSV input contract

**Files:**
- Modify: `tests/test_naver_image_collector.py`
- Modify only if the new test exposes a gap: `naver_image_collector.py`

**Interfaces:**
- Consumes: `load_keywords(file_path: str | Path) -> list[str]`
- Produces: Ordered, trimmed, non-empty, unique search terms from the `keyword` column.

- [ ] **Step 1: Write the failing or contract test**

```python
def test_load_keywords_from_csv_accepts_header_variants_and_preserves_order(self):
    root = self._tmp_dir()
    csv_path = root / "keywords.csv"
    csv_path.write_text(
        f" Keyword \n  {KOREAN_KEYWORD}  \n\n{KOREAN_OTHER}\n{KOREAN_KEYWORD}\n",
        encoding="utf-8-sig",
    )

    self.assertEqual(load_keywords(csv_path), [KOREAN_KEYWORD, KOREAN_OTHER])
```

- [ ] **Step 2: Run the focused test and inspect its result**

Run: `python -m unittest tests.test_naver_image_collector.BatchInputTests.test_load_keywords_from_csv_accepts_header_variants_and_preserves_order -v`

Expected: PASS if the existing loader already fully satisfies the approved contract; otherwise FAIL specifically on header normalization, trimming, order, or deduplication.

- [ ] **Step 3: If RED, implement only the missing loader behavior**

Keep `_load_keywords_from_csv()` resolving headers case-insensitively and `_dedupe_keywords()` trimming values, skipping blanks, and retaining first-occurrence order. Do not broaden the accepted schema beyond `keyword`.

- [ ] **Step 4: Run the focused test again**

Run: `python -m unittest tests.test_naver_image_collector.BatchInputTests -v`

Expected: all `BatchInputTests` pass.

### Task 2: Validate, preview, cache, and execute the uploaded CSV

**Files:**
- Modify: `tests/test_naver_image_collector.py`
- Modify: `naver_image_collector.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `NaverImageCollectorGUI._validate_batch_file(file_path: str) -> list[str]`
- Changes: `NaverImageCollectorGUI._run_batch_task(keywords: list[str], limit: int, min_thumbnail_size: int) -> None`
- Stores: `batch_keywords: list[str]` and `validated_batch_file: str`

- [ ] **Step 1: Write failing GUI workflow tests**

Add a tiny `FakeVar` test helper and tests equivalent to:

```python
def test_validate_batch_file_caches_keywords_and_logs_preview(self):
    gui = NaverImageCollectorGUI.__new__(NaverImageCollectorGUI)
    gui.batch_file_var = FakeVar("")
    gui.batch_keywords = []
    gui.validated_batch_file = ""
    messages = []
    gui._append_log = messages.append

    keywords = gui._validate_batch_file(str(csv_path))

    self.assertEqual(keywords, [KOREAN_KEYWORD, KOREAN_OTHER])
    self.assertEqual(gui.batch_keywords, keywords)
    self.assertEqual(gui.validated_batch_file, str(csv_path))
    self.assertIn(KOREAN_KEYWORD, messages[-1])

def test_start_batch_run_passes_cached_keywords_to_background_task(self):
    gui = build_test_gui_with_cached_keywords([KOREAN_KEYWORD, KOREAN_OTHER])
    calls = []
    gui._run_in_thread = lambda target, *args: calls.append((target, args))

    gui._start_batch_run()

    self.assertEqual(calls[0][1][0], [KOREAN_KEYWORD, KOREAN_OTHER])
```

- [ ] **Step 2: Verify the GUI tests fail because the workflow is missing**

Run: `python -m unittest tests.test_naver_image_collector.GuiBatchUploadTests -v`

Expected: FAIL because `_validate_batch_file` and cache attributes do not exist, or because `_start_batch_run` still passes a path rather than parsed terms.

- [ ] **Step 3: Implement the minimum GUI workflow**

In `__init__`, initialize:

```python
self.batch_keywords: list[str] = []
self.validated_batch_file = ""
```

Implement validation and preview:

```python
def _validate_batch_file(self, file_path: str) -> list[str]:
    keywords = load_keywords(file_path)
    self.batch_file_var.set(file_path)
    self.batch_keywords = keywords
    self.validated_batch_file = file_path
    self._append_log(f"CSV loaded: {len(keywords)} keywords / first: {keywords[0]}")
    return keywords
```

Make `_choose_batch_file()` call this method and display a clear dialog on `OSError`, `ValueError`, or `RuntimeError`. Make `_start_batch_run()` revalidate only when the editable path differs from `validated_batch_file`, then pass a copy of `batch_keywords` into `_run_in_thread`. Change `_run_batch_task()` to receive that list directly and call `run_batch_collection()` without rereading the file.

Relabel the batch buttons to `Upload CSV` and `Search images`, while retaining XLSX in the file picker for backward compatibility.

- [ ] **Step 4: Run focused and full tests**

Run: `python -m unittest tests.test_naver_image_collector.GuiBatchUploadTests -v`

Expected: all GUI upload tests pass.

Run: `python -m unittest discover -v`

Expected: the full suite passes with zero failures and errors.

- [ ] **Step 5: Update usage documentation**

Document that selecting a CSV validates and previews the `keyword` rows, and that `Search images` processes every valid unique row in order.

- [ ] **Step 6: Compile and verify the final diff**

Run: `python -m py_compile naver_image_collector.py`

Expected: exit code 0.

Run: `git diff --check`

Expected: no whitespace errors.
