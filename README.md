# Naver Image Collector

Search Naver Images by keyword, save thumbnail images into folders, and keep source/original URL metadata in both CSV and JSON.

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
- CSV/XLSX batch search
- Output folder selection
- Image limit selection, default `20`
- Optional visible browser mode for troubleshooting
- Progress logs

## CLI

Single keyword:

```powershell
python .\naver_image_collector.py --keyword "수면안대" --limit 20
```

CSV batch:

```powershell
python .\naver_image_collector.py --batch-file .\sample_keywords.csv --limit 20
```

Custom output folder:

```powershell
python .\naver_image_collector.py --keyword "핸드크림" --output-dir .\downloaded_images
```

Show browser:

```powershell
python .\naver_image_collector.py --keyword "수면안대" --show-browser
```

## CSV Format

CSV and XLSX batch files need a `keyword` header:

```csv
keyword
수면안대
핸드크림
```

Blank rows are skipped. Duplicate keywords are processed once.

## Output

Each keyword writes to a safe folder under the output root:

```text
downloaded_images/<keyword>/
  image_01.jpg
  image_02.jpg
  metadata.csv
  metadata.json
```

The app saves Naver thumbnail images locally. Metadata includes:

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
