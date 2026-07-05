# Naver Image Collector

Search Naver Images by keyword, save thumbnail images into folders, and keep source/original URL metadata in both CSV and JSON.

The collector requests Naver Image Search with latest-date sorting (`sort=date`) by default. Naver controls the final ordering, so this is best understood as "ask Naver for latest results first" rather than a guaranteed EXIF/date sort of every image file.

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
- Image limit selection, default `50`
- Optional visible browser mode for troubleshooting
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

## Output

Each keyword writes to a safe folder under the output root:

```text
downloaded_images/<keyword>/
  image_01.png
  image_02.png
  metadata.csv
  metadata.json
```

The app saves Naver thumbnail images locally as PNG files. Metadata includes:

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
