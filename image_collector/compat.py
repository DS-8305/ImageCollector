from __future__ import annotations
import csv, hashlib, json, re
from dataclasses import asdict, dataclass
from pathlib import Path
from io import BytesIO
from urllib.parse import quote_plus
import requests
from PIL import Image
from .batch_input import load_keywords
from .models import CollectionOptions
from .gui import CollectorGUI
DEFAULT_LIMIT=50
DEFAULT_OUTPUT_DIR="downloaded_images"
DEFAULT_MIN_THUMBNAIL_SIZE=150
METADATA_FIELDS=["keyword","index","file_name","thumbnail_url","source_url","title","source","status","error"]
IMAGE_FILE_PATTERN=re.compile(r"^image_\d+\.(jpg|jpeg|png|webp)$",re.I)

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


@dataclass(slots=True)
class ImageCandidate:
    thumbnail_url: str
    source_url: str
    title: str
    source: str


@dataclass(frozen=True, slots=True)
class BatchResult:
    keyword: str
    saved_count: int
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


def clear_generated_images(folder_path: str | Path) -> None:
    folder = Path(folder_path)
    if not folder.exists():
        return
    for child in folder.iterdir():
        if child.is_file() and IMAGE_FILE_PATTERN.match(child.name):
            child.unlink()


def _log_adapter(logger):
    return lambda event: logger(event.get("message") or str(event)) if logger else None

def collect_single_keyword(keyword, *, limit=50, output_root=DEFAULT_OUTPUT_DIR, headless=True,
                           min_thumbnail_size=150, logger=None):
    from .runner import run_collection
    result=run_collection([keyword],CollectionOptions(limit=limit,headless=headless,
        min_width=min_thumbnail_size,min_height=min_thumbnail_size),output_root,logger=_log_adapter(logger))
    job=result.jobs[0]
    if job.status in ("failed","needs_attention"):
        raise RuntimeError(job.error)
    return sorted((result.run_dir/job.folder).glob("image_*.png"))

def run_batch_collection(keywords, *, limit=50, output_root=DEFAULT_OUTPUT_DIR, headless=True,
                         min_thumbnail_size=150, logger=None, collector_func=None):
    if collector_func is None:
        from .runner import run_collection
        result=run_collection(keywords,CollectionOptions(limit=limit,headless=headless,
            min_width=min_thumbnail_size,min_height=min_thumbnail_size),output_root,logger=_log_adapter(logger))
        return [BatchResult(j.keyword,j.saved_count,j.status,j.error) for j in result.jobs]
    results=[]
    for keyword in dict.fromkeys(k.strip() for k in keywords if k.strip()):
        try:
            count=len(collector_func(keyword,limit,Path(output_root),headless,min_thumbnail_size))
            status="success" if count>=limit else "partial" if count else "failed"
            results.append(BatchResult(keyword,count,status,"" if count else "저장된 이미지가 없습니다."))
        except Exception as exc:
            results.append(BatchResult(keyword,0,"failed",str(exc)))
    return results

class NaverImageCollector:
    def __init__(self, *, output_root=DEFAULT_OUTPUT_DIR, headless=True, timeout_seconds=20,
                 min_thumbnail_size=150, logger=None, driver=None):
        self.output_root=Path(output_root)
        self.headless=headless
        self.timeout_seconds=timeout_seconds
        self.min_thumbnail_size=min_thumbnail_size
        self.logger=logger
        self.driver=driver
        self.session=requests.Session()
        self._browser=None

    def _build_driver(self):
        from .browser import BrowserSession
        self._browser=BrowserSession(self.headless)
        return self._browser.driver

    def close(self):
        self.session.close()
        if self._browser:
            self._browser.close()

    def collect_keyword(self, keyword, *, limit=50):
        from .runner import run_collection
        factory=None
        if self.driver is not None:
            from .providers import create_provider
            class Injected:
                driver=self.driver
            injected=Injected()
            factory=lambda engine, options, browser, **kwargs: create_provider(engine,options,injected,**kwargs)
        result=run_collection([keyword],CollectionOptions(limit=limit,headless=self.headless,
            min_width=self.min_thumbnail_size,min_height=self.min_thumbnail_size),self.output_root,
            logger=_log_adapter(self.logger),provider_factory=factory)
        job=result.jobs[0]
        if job.status in ("failed","needs_attention"):
            raise RuntimeError(job.error)
        return sorted((result.run_dir/job.folder).glob("image_*.png"))

    def _search_url(self, keyword):
        return f"https://search.naver.com/search.naver?where=image&sm=tab_opt&sort=date&query={quote_plus(keyword)}"

    def _download_thumbnail(self, url, file_path):
        response=self.session.get(url,timeout=getattr(self,"timeout_seconds",20))
        response.raise_for_status()
        with Image.open(BytesIO(response.content)) as image:
            if image.width<self.min_thumbnail_size or image.height<self.min_thumbnail_size:
                raise ValueError("Image is smaller than minimum size.")
            image.convert("RGBA").save(file_path,"PNG",optimize=True)

class NaverImageCollectorGUI(CollectorGUI):
    def __init__(self, root):
        super().__init__(root)
        import tkinter as tk
        self.batch_keywords=[]
        self.validated_batch_file=""
        self.min_thumbnail_size_var=tk.StringVar(value="150")
        self.output_dir_var=self.output_var

    def _append_log(self, message):
        self.events.put({"type":"log","message":str(message)})

    def _run_in_thread(self, target, *args):
        settings=(self.output_dir_var.get().strip() or DEFAULT_OUTPUT_DIR,not self.show_browser_var.get())
        self.start_task(lambda stop,emit: target(*args,settings=settings,stop=stop,emit=emit))

    def _run_batch_task(self, keywords, limit, min_thumbnail_size, *, settings, stop, emit):
        from .runner import run_collection
        root,headless=settings
        return run_collection(keywords,CollectionOptions(limit=limit,headless=headless,
            min_width=min_thumbnail_size,min_height=min_thumbnail_size),root,stop_event=stop,logger=emit)

    def _choose_batch_file(self) -> None:
        from tkinter import filedialog

        file_path = filedialog.askopenfilename(
            title="Choose CSV or XLSX",
            filetypes=[("Batch files", "*.csv;*.xlsx"), ("All files", "*.*")],
        )
        if file_path:
            try:
                self._validate_batch_file(file_path)
            except (OSError, ValueError, RuntimeError) as exc:
                self._report_batch_validation_error(exc)

    def _validate_batch_file(self, file_path: str) -> list[str]:
        keywords = load_keywords(file_path)
        self.batch_file_var.set(file_path)
        self.batch_keywords = keywords
        self.validated_batch_file = file_path
        self._append_log(f"CSV loaded: {len(keywords)} keywords / first: {keywords[0]}")
        return keywords

    def _report_batch_validation_error(self, error: Exception) -> None:
        from tkinter import messagebox

        self._append_log(f"Batch file validation failed: {error}")
        messagebox.showerror("Batch file error", str(error))

    def _parse_limit(self) -> int:
        try:
            limit = int(self.limit_var.get().strip())
        except ValueError as exc:
            raise ValueError("Limit must be a number.") from exc
        if limit < 1:
            raise ValueError("Limit must be at least 1.")
        return limit

    def _parse_min_thumbnail_size(self) -> int:
        try:
            min_size = int(self.min_thumbnail_size_var.get().strip())
        except ValueError as exc:
            raise ValueError("Min size must be a number.") from exc
        if min_size < 1:
            raise ValueError("Min size must be at least 1.")
        return min_size

    def _start_batch_run(self) -> None:
        from tkinter import messagebox

        batch_file = self.batch_file_var.get().strip()
        if not batch_file:
            messagebox.showerror("Input error", "Choose a CSV or XLSX file.")
            return
        try:
            limit = self._parse_limit()
            min_thumbnail_size = self._parse_min_thumbnail_size()
        except ValueError as exc:
            messagebox.showerror("Input error", str(exc))
            return
        if batch_file != self.validated_batch_file:
            try:
                self._validate_batch_file(batch_file)
            except (OSError, ValueError, RuntimeError) as exc:
                self._report_batch_validation_error(exc)
                return
        self._run_in_thread(self._run_batch_task, list(self.batch_keywords), limit, min_thumbnail_size)


def build_parser():
    from .cli import build_parser as modern_parser
    parser=modern_parser()
    parser.set_defaults(limit=50,output_dir=DEFAULT_OUTPUT_DIR,min_thumbnail_size=150)
    return parser
