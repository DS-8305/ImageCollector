# Naver Image Collector Design

## Goal

Build a Python desktop program that searches Naver Image Search by keyword, downloads thumbnail images into keyword-specific folders, and saves original/source URL metadata for review and later reuse.

The new `Image_collector` project should borrow the practical shape of `Review_Extracting_Practice_V03`: a Tkinter GUI for everyday use, CLI support for automation, CSV batch processing, logs, predictable output folders, and focused unit tests.

## Scope

The first version supports:

- Single keyword collection from the GUI.
- CSV batch collection from a `keyword` column.
- CLI execution for one keyword or one CSV file.
- Default image limit of 20 images per keyword.
- Thumbnail image download.
- Metadata export as both CSV and JSON.
- Optional visible browser mode for troubleshooting.

The first version does not try to download full-size originals. It records original/source URLs when Naver exposes them, while storing thumbnails as the reliable local image files.

## Architecture

Use a compact Python structure:

- `naver_image_collector.py`: collection engine, CSV loader, metadata writer, CLI parser, and Tkinter GUI.
- `requirements.txt`: runtime dependencies.
- `README.md`: GUI and CLI usage.
- `sample_keywords.csv`: example batch input with a `keyword` header.
- `tests/test_naver_image_collector.py`: network-free tests for safe filenames, CSV loading, output naming, and metadata writing.

The GUI is the default user path. Running `python .\naver_image_collector.py` with no arguments opens the GUI. CLI arguments are available for repeatable automation.

## GUI Design

The GUI uses Tkinter and follows the reference project's simple desktop style:

- Single search section: keyword input, image limit input, visible browser checkbox, and run button.
- CSV batch section: file picker and batch run button.
- Output folder section: defaults to `downloaded_images`, with a folder picker for custom output.
- Log section: shows progress, saved counts, skipped items, errors, and final summaries.
- Execution safety: collection runs on a background thread so the UI stays responsive. Buttons are disabled while a run is active and restored when the run finishes.

## Data Flow

For a single keyword:

1. Normalize the keyword and create `downloaded_images/<safe_keyword>/`.
2. Open Naver Image Search with Selenium.
3. Scroll until enough image result candidates are collected or no more useful results appear.
4. Extract each candidate's thumbnail URL, source/original URL when available, title, source text, and result index.
5. Download thumbnails until the requested limit is reached.
6. Save metadata as `metadata.csv` and `metadata.json` in the keyword folder.
7. Log the final saved count.

For CSV batch:

1. Read `.csv` or `.xlsx` files.
2. Require a `keyword` header.
3. Process valid non-empty keywords in order.
4. Continue to the next keyword if one keyword fails.
5. Log a final success/failure summary.

## Output Format

Each keyword writes to:

```text
downloaded_images/<safe_keyword>/
  image_01.jpg
  image_02.jpg
  ...
  metadata.csv
  metadata.json
```

Metadata fields:

- `keyword`
- `index`
- `file_name`
- `thumbnail_url`
- `source_url`
- `title`
- `source`
- `status`
- `error`

The local image file uses the thumbnail URL because it is the most stable download target. `source_url` records the original or source page URL that Naver exposes for later manual checking.

## Error Handling

- If Naver returns fewer than the requested count, save what was collected and log a warning.
- If an image download fails, record the error in metadata and continue.
- If a CSV row has an empty keyword, skip it and log the skip.
- If the browser fails to start, show a GUI error dialog or raise a CLI error.
- If Naver changes its page structure, fail with a clear message that selectors may need updating.

## Testing

Unit tests should avoid live Naver network access. Cover:

- Safe folder name generation for Korean, spaces, and punctuation.
- CSV loading with `keyword` header and empty-row skipping.
- Metadata CSV and JSON writing.
- Existing generated image cleanup or overwrite behavior.
- CLI argument defaults where practical.

Manual verification covers the live browser path:

- GUI single keyword run saves up to 20 thumbnails.
- GUI CSV batch run creates separate keyword folders.
- CLI single keyword run works.
- CLI CSV batch run works.

## Acceptance Criteria

- `python .\naver_image_collector.py` opens the GUI.
- A single GUI keyword run downloads thumbnails into `downloaded_images/<keyword>/`.
- Each keyword folder includes `metadata.csv` and `metadata.json`.
- CSV batch mode processes multiple keywords without stopping the whole batch on one failure.
- CLI single and batch modes work.
- Network-free unit tests pass.
