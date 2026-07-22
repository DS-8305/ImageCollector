# Strict Image Relevance Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save only Naver image-result candidates whose title or result-card text contains the complete normalized search keyword.

**Architecture:** Add pure relevance normalization and candidate predicate functions, then apply them while scrolling so unrelated results never reach the download loop. Restrict browser extraction to Naver image-viewer result grids and their thumbnail IDs, parse the associated result metadata, and remove forced date sorting; preserve all existing input, output, and batch interfaces.

**Tech Stack:** Python 3, Selenium JavaScript execution, `unittest`; no new dependencies.

## Global Constraints

- Precision is more important than reaching the requested image count.
- Require the complete normalized keyword in title/source evidence.
- Never fall back to page-wide `img` extraction or relax relevance rules.
- Keep CSV/XLSX, CP949/UTF-8, GUI, CLI, metadata, folder, and image-size behavior compatible.
- Automated tests must not require network or a real browser.

---

### Task 1: Add deterministic relevance rules

**Files:**
- Modify: `tests/test_naver_image_collector.py`
- Modify: `naver_image_collector.py`

**Interfaces:**
- Produces: `normalize_relevance_text(value: str) -> str`
- Produces: `is_candidate_relevant(keyword: str, candidate: ImageCandidate) -> bool`

- [ ] **Step 1: Write failing normalization and predicate tests**

```python
def test_normalize_relevance_text_ignores_spacing_punctuation_and_case(self):
    self.assertEqual(normalize_relevance_text(" Sleep-mask! "), "sleepmask")
    self.assertEqual(normalize_relevance_text("이준석 국회의원"), "이준석국회의원")

def test_candidate_relevance_requires_complete_normalized_keyword(self):
    candidate = ImageCandidate(
        thumbnail_url="https://search.pstatic.net/thumb.jpg",
        source_url="https://example.com",
        title="이준석 국회의원 인터뷰",
        source="뉴스",
    )
    self.assertTrue(is_candidate_relevant("이준석국회의원", candidate))
    self.assertFalse(is_candidate_relevant("박홍근 장관", candidate))

def test_candidate_relevance_rejects_empty_evidence(self):
    candidate = ImageCandidate("thumb", "source", "", "")
    self.assertFalse(is_candidate_relevant("이준석국회의원", candidate))
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_naver_image_collector.RelevanceFilterTests -v`

Expected: import failure because the relevance functions do not exist.

- [ ] **Step 3: Implement the minimum pure functions**

```python
def normalize_relevance_text(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def is_candidate_relevant(keyword: str, candidate: ImageCandidate) -> bool:
    normalized_keyword = normalize_relevance_text(keyword)
    evidence = normalize_relevance_text(f"{candidate.title} {candidate.source}")
    return bool(normalized_keyword and evidence and normalized_keyword in evidence)
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m unittest tests.test_naver_image_collector.RelevanceFilterTests -v`

Expected: all relevance tests pass.

### Task 2: Restrict extraction to Naver image-viewer results

**Files:**
- Modify: `tests/test_naver_image_collector.py`
- Modify: `naver_image_collector.py`

**Interfaces:**
- Consumes: `NaverImageCollector.driver.execute_script(script: str)`
- Produces: `NaverImageCollector._extract_candidates_from_page() -> list[ImageCandidate]`

- [ ] **Step 1: Write a failing extraction-scope test**

Use a fake driver that records the JavaScript and returns one result dictionary:

```python
def test_page_extraction_scopes_to_naver_image_viewer_results(self):
    driver = RecordingDriver([{
        "thumbnailUrl": "https://search.pstatic.net/common/thumb.jpg",
        "sourceUrl": "https://example.com/article",
        "title": "이준석 국회의원",
        "source": "뉴스 결과",
    }])
    collector = NaverImageCollector.__new__(NaverImageCollector)
    collector.driver = driver

    candidates = collector._extract_candidates_from_page()

    self.assertEqual(len(candidates), 1)
    self.assertIn("querySelectorAll('[data-image-viewer-list]')", driver.script)
    self.assertIn("img[data-image-viewer-img-id]", driver.script)
    self.assertIn("search.pstatic.net", driver.script)
    self.assertNotIn("querySelectorAll('img')", driver.script)
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest tests.test_naver_image_collector.ResultExtractionTests -v`

Expected: FAIL because the script still contains page-wide `querySelectorAll('img')`.

- [ ] **Step 3: Implement strict structural extraction**

Query `[data-image-viewer-list]` result grids and their `img[data-image-viewer-img-id]` thumbnails. Parse the grid's JSON metadata and join each thumbnail ID to its title, source, writer domain, and original link. Require a parsed thumbnail hostname equal to `search.pstatic.net`; skip invalid URLs. Return the same candidate dictionary keys used by Python. Do not add a page-wide fallback.

- [ ] **Step 4: Run extraction tests and verify GREEN**

Run: `python -m unittest tests.test_naver_image_collector.ResultExtractionTests -v`

Expected: all extraction tests pass.

### Task 3: Filter during scrolling and prefer relevance ordering

**Files:**
- Modify: `tests/test_naver_image_collector.py`
- Modify: `naver_image_collector.py`
- Modify: `README.md`

**Interfaces:**
- Changes: `NaverImageCollector._collect_candidates(keyword: str, limit: int) -> list[ImageCandidate]`
- Changes caller: `NaverImageCollector.collect_keyword(keyword: str, *, limit: int) -> list[Path]`

- [ ] **Step 1: Write failing collection behavior tests**

Use a collector created with `__new__`, a fake driver, a queued `_extract_candidates_from_page`, and captured log messages. Verify:

```python
def test_collect_candidates_keeps_only_relevant_items_in_order(self):
    candidates = collector._collect_candidates("이준석국회의원", 3)
    self.assertEqual([item.title for item in candidates], [
        "이준석 국회의원 인터뷰",
        "오늘의 이준석국회의원 일정",
    ])
    self.assertTrue(any("excluded 1" in message for message in messages))

def test_collect_candidates_raises_when_no_result_cards_exist(self):
    with self.assertRaisesRegex(RuntimeError, "result cards"):
        collector._collect_candidates("이준석국회의원", 3)

def test_search_url_does_not_force_latest_sort(self):
    url = collector._search_url("keyword")
    self.assertNotIn("sort=date", url)
    self.assertIn("where=image", url)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_naver_image_collector.StrictCandidateCollectionTests tests.test_naver_image_collector.SearchUrlTests -v`

Expected: FAIL because `_collect_candidates` lacks the keyword argument, keeps unrelated candidates, and the URL forces date sorting.

- [ ] **Step 3: Implement strict collection**

Pass `keyword` into `_collect_candidates`. Deduplicate every extracted thumbnail URL, count rejected unique candidates, and append only items accepted by `is_candidate_relevant`. Stop early only when `limit` relevant candidates have been found. Track stale rounds using the seen-candidate count from consecutive extraction passes, then scroll for the next pass. If no raw candidates were ever seen, raise `RuntimeError("No image result cards were found. Naver page selectors may need updating.")`. Log the rejected count before returning.

Change `_search_url()` to omit `sort=date`. Update the insufficient-results warning to mention strict filtering.

- [ ] **Step 4: Run focused and full tests**

Run: `python -m unittest tests.test_naver_image_collector.StrictCandidateCollectionTests tests.test_naver_image_collector.SearchUrlTests -v`

Expected: all focused tests pass.

Run: `python -m unittest discover -v`

Expected: the full suite passes with zero failures and errors.

- [ ] **Step 5: Update documentation**

Replace the README's latest-date description with strict relevance behavior, including that fewer images may be saved and that no unrelated fallback is used.

- [ ] **Step 6: Final verification**

Run: `python -m py_compile naver_image_collector.py`

Expected: exit code 0.

Run: `git diff --check`

Expected: no whitespace errors.
