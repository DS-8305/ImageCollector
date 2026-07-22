# Naver Image Collector

Search Naver Images by keyword, save thumbnail images into folders, and keep source/original URL metadata in both CSV and JSON.

The collector uses Naver's default image-search ordering and applies strict
relevance filtering. It extracts Naver image-viewer result thumbnails and saves a
candidate only when its title or result-card text contains the complete
normalized keyword. The app may therefore save fewer images than requested
instead of filling a folder with unrelated results.

## Install

```powershell
python -m pip install -r .\requirements.txt
```

Chrome must be installed. `webdriver-manager` downloads the matching ChromeDriver automatically.

## GUI

Run without arguments to open the desktop UI:

```powershell
python .\naver_image_collector.py
```

The GUI supports:

- Single keyword search
- CSV/XLSX batch search with upload-time validation and keyword preview
- Output folder selection
- Image limit selection, default `50`
- Minimum thumbnail size selection, default `150px`
- Optional visible browser mode for troubleshooting
- Strict keyword relevance filtering without an unrelated-image fallback
- Progress logs

## CLI

Single keyword:

```powershell
python .\naver_image_collector.py --keyword "sleep mask"
```

CSV batch:

```powershell
python .\naver_image_collector.py --batch-file .\sample_keywords.csv
```

Custom limit:

```powershell
python .\naver_image_collector.py --keyword "sleep mask" --limit 50
```

Custom minimum thumbnail size:

```powershell
python .\naver_image_collector.py --keyword "sleep mask" --min-thumbnail-size 150
```

Custom output folder:

```powershell
python .\naver_image_collector.py --keyword "hand cream" --output-dir .\downloaded_images
```

Show browser:

```powershell
python .\naver_image_collector.py --keyword "sleep mask" --show-browser
```

## CSV Format

CSV and XLSX batch files need a `keyword` header:

```csv
keyword
sleep mask
hand cream
```

Blank rows are skipped. Duplicate keywords are processed once.
CSV files saved as UTF-8 or Windows Korean CP949 are supported.

In the GUI, select `Upload CSV` and choose the file. The log confirms the
number of valid keywords and previews the first keyword. Then select
`Search images` to process every valid unique keyword from row 2 onward in
the same order as the file. Choosing a file alone does not start a search.

## Output

Each keyword writes to a safe folder under the output root:

```text
downloaded_images/<keyword>/
  image_01.png
  image_02.png
  metadata.csv
  metadata.json
```

The app saves Naver thumbnail images locally as PNG files. Images smaller than the configured minimum width or height are skipped. Metadata includes:

- `keyword`
- `index`
- `file_name`
- `thumbnail_url`
- `source_url`
- `title`
- `source`
- `status`
- `error`

## Tests

```powershell
python -m unittest discover -v
```
