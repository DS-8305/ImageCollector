"""Crash-aware run records and immutable outputs."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from io import BytesIO, StringIO
from pathlib import Path

from PIL import Image

from .models import Candidate, CollectionOptions, DownloadedImage

FIELDS = ["keyword","index","file_name","thumbnail_url","source_url","title","source","status","error",
          "schema_version","run_id","engine","candidate_id","search_rank","original_url","downloaded_url",
          "download_kind","width","height","format","byte_size","content_hash","collected_at","fallback_reason",
          "license_url","license_status","profile","min_width","min_height","min_long_edge"]
IMAGE_NAME = re.compile(r"^image_\d+\.png$")
TERMINAL = {"success","partial","empty","failed","needs_attention","cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_keyword_name(keyword: str) -> str:
    slug = re.sub(r"[^\w-]+", "_", keyword.strip(), flags=re.UNICODE).strip("_")[:40] or "keyword"
    return "kw_" + slug + "_" + hashlib.sha256(keyword.strip().encode("utf-8")).hexdigest()[:16]


def atomic_bytes(path: Path, content: bytes, *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    try:
        with temporary.open("xb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        for attempt in range(6):
            try:
                if overwrite:
                    os.replace(temporary, path)
                else:
                    # Windows rename never replaces an existing name; POSIX link
                    # gives the same no-clobber atomic creation semantics.
                    if os.name == "nt":
                        os.rename(temporary, path)
                    else:
                        os.link(temporary, path)
                break
            except PermissionError as exc:
                # Windows sync/indexing processes can briefly hold the destination.
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, data) -> None:
    atomic_bytes(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def pixel_hash(content: bytes) -> str:
    with Image.open(BytesIO(content)) as image:
        rgba = image.convert("RGBA")
        return hashlib.sha256(f"{rgba.width}x{rgba.height}:".encode() + rgba.tobytes()).hexdigest()


def within_run(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("실행 기록에 올바르지 않은 파일 경로가 있습니다.")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or target == root.resolve():
        raise ValueError("실행 기록의 경로가 결과 폴더 밖을 가리킵니다.")
    return target


def load_run(path: str | Path) -> dict:
    root = Path(path).resolve()
    if root.name == "run.json":
        root = root.parent
    try:
        with (root / "run.json").open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"실행 기록을 읽을 수 없습니다: {root}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        raise ValueError("지원하지 않는 실행 기록 형식입니다.")
    if not isinstance(data.get("keywords"), list) or not data["keywords"] or not all(isinstance(k,str) and k.strip() for k in data["keywords"]):
        raise ValueError("실행 기록의 검색어가 올바르지 않습니다.")
    if not isinstance(data.get("jobs"), dict) or not isinstance(data.get("options"),dict):
        raise ValueError("실행 기록의 작업 설정이 올바르지 않습니다.")
    try:
        options = CollectionOptions(**data["options"])
        for engine in options.engines:
            options.resolve(engine)
    except (ValueError, TypeError) as exc:
        raise ValueError("실행 기록의 수집 옵션이 올바르지 않습니다.") from exc
    expected = {(k, e) for k in data["keywords"] for e in options.engines}
    actual = set()
    for job in data["jobs"].values():
        if not isinstance(job,dict) or not isinstance(job.get("records"),list):
            raise ValueError("실행 기록의 작업이 올바르지 않습니다.")
        identity = (job.get("keyword"),job.get("engine"))
        if identity not in expected or identity in actual:
            raise ValueError("실행 기록의 작업 식별자가 올바르지 않습니다.")
        actual.add(identity)
        folder = within_run(root, job.get("folder"))
        for row in job["records"]:
            if not isinstance(row,dict):
                raise ValueError("실행 기록의 이미지 정보가 올바르지 않습니다.")
            name = row.get("file_name","")
            if name:
                if not isinstance(name,str) or not IMAGE_NAME.fullmatch(name):
                    raise ValueError("실행 기록의 이미지 파일명이 올바르지 않습니다.")
                within_run(root, str(folder.relative_to(root) / name))
    if actual != expected:
        raise ValueError("실행 기록에 누락된 작업이 있습니다.")
    return data




class RunStore:
    def __init__(self, run_dir: Path, data: dict):
        self.run_dir = run_dir.resolve()
        self.data = data
        self._locked = False
        self._lock_handle = None

    @classmethod
    def create(cls, keywords, options: CollectionOptions, output_root, selected_candidates=None):
        keywords = list(dict.fromkeys(k.strip() for k in keywords if k.strip()))
        if not keywords:
            raise ValueError("검색어가 없습니다.")
        resolved = {engine: options.resolve(engine) for engine in options.engines}
        run_id = "run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:12]
        root = Path(output_root).resolve() / run_id
        root.mkdir(parents=True, exist_ok=False)
        data = {"schema_version":2,"run_id":run_id,"created_at":utc_now(),"updated_at":utc_now(),
                "options":asdict(options),"keywords":keywords,"jobs":{},"status":"pending"}
        folders = set()
        for keyword in keywords:
            for engine in options.engines:
                job_id = hashlib.sha256((keyword+"|"+engine).encode()).hexdigest()
                folder = safe_keyword_name(keyword) + "/" + engine
                if folder.casefold() in folders:
                    raise ValueError("검색어 폴더 해시가 충돌했습니다. 검색어를 구분해 다시 실행하세요.")
                folders.add(folder.casefold())
                data["jobs"][job_id] = {
                    "keyword":keyword,"engine":engine,"folder":folder,"status":"pending","error":"",
                    "requested_count":options.limit,"resolved_options":asdict(resolved[engine]),"records":[]}
                if selected_candidates is not None:
                    data["jobs"][job_id]["selected_candidates"] = [asdict(c) for c in selected_candidates]
        store = cls(root,data)
        store.acquire()
        try:
            store.checkpoint()
        except Exception:
            store.close()
            raise
        return store

    @classmethod
    def open(cls, path):
        root = Path(path).resolve()
        if root.name == "run.json":
            root = root.parent
        data = load_run(root)
        store = cls(root,data)
        store.acquire()
        try:
            store.recover()
        except Exception:
            store.close()
            raise
        return store

    def acquire(self):
        lock = self.run_dir / "run.lock"
        handle = lock.open("a+b")
        try:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("이 결과는 다른 실행에서 사용 중이거나 잠금을 확보할 수 없습니다.") from exc
        self._lock_handle = handle
        self._locked = True

    def close(self):
        if self._locked:
            # Closing releases the OS lock even after a process crash; never unlink
            # the shared lock inode, which could let another owner enter early.
            self._lock_handle.close()
            self._lock_handle = None
            self._locked = False

    def job_folder(self, job):
        return within_run(self.run_dir,job["folder"])

    def checkpoint(self):
        self.data["updated_at"] = utc_now()
        atomic_json(self.run_dir / "run.json",self.data)

    def recover(self):
        for job in self.data["jobs"].values():
            changed = False
            for row in job["records"]:
                if row.get("status") not in ("saved","pending"):
                    continue
                try:
                    path = self.job_folder(job) / row["file_name"]
                    if not path.is_file():
                        raise ValueError("저장 이미지 파일이 없습니다.")
                    content = path.read_bytes()
                    if pixel_hash(content) != row["content_hash"]:
                        raise ValueError("저장 이미지가 변경되었거나 손상되었습니다.")
                    row.update(status="saved",error="")
                except (OSError, ValueError, KeyError) as exc:
                    row.update(status="failed",error=str(exc),file_name="")
                    if job["status"] == "success":
                        job["status"] = "partial"
                    changed = True
            if changed or job.get("status") == "running":
                job["status"] = "partial" if self.saved_rows(job) else "pending"
            self.export_job(job)
        self.checkpoint()

    @staticmethod
    def saved_rows(job):
        return [row for row in job["records"] if row.get("status") == "saved"]

    def candidate_row(self, job, candidate):
        options = job["resolved_options"]
        return {"keyword":job["keyword"],"index":len(job["records"])+1,"file_name":"",
                "thumbnail_url":candidate.thumbnail_url,"source_url":candidate.source_url,
                "title":candidate.title,"source":candidate.source,"status":"pending","error":"",
                "schema_version":2,"run_id":self.data["run_id"],"engine":job["engine"],
                "candidate_id":candidate.candidate_id,"search_rank":candidate.rank,
                "original_url":candidate.original_url or None,"downloaded_url":"","download_kind":"",
                "width":0,"height":0,"format":"","byte_size":0,"content_hash":"","collected_at":utc_now(),
                "fallback_reason":"","license_url":candidate.license_url,
                "license_status":"provided" if candidate.license_url else "unknown",
                "profile":options["profile"],"min_width":options["min_width"],"min_height":options["min_height"],
                "min_long_edge":options["min_long_edge"]}

    def begin_image(self, job, candidate: Candidate, image: DownloadedImage):
        row = self.candidate_row(job,candidate)
        used = [int(r["file_name"][6:-4]) for r in job["records"] if IMAGE_NAME.fullmatch(r.get("file_name",""))]
        name = f"image_{max(used,default=0)+1:02d}.png"
        index = max(used,default=0)+1
        folder = self.job_folder(job)
        while (folder/name).exists() or (folder/name).is_symlink():
            index += 1
            name = f"image_{index:02d}.png"
        row.update(file_name=name,width=image.width,height=image.height,format="PNG",
                   byte_size=len(image.png_bytes),content_hash=image.content_hash,
                   downloaded_url=image.downloaded_url,download_kind=image.download_kind,
                   fallback_reason=image.fallback_reason)
        job["records"].append(row)
        self.checkpoint()
        return row

    def commit_image(self, job, row, image):
        atomic_bytes(self.job_folder(job)/row["file_name"],image.png_bytes,overwrite=False)
        row.update(status="saved",error="")
        self.checkpoint()

    def record_error(self,job,candidate,status,error):
        row = self.candidate_row(job,candidate)
        row.update(status=status,error=str(error))
        job["records"].append(row)
        self.checkpoint()

    def export_job(self,job):
        folder = self.job_folder(job)
        atomic_json(folder/"metadata.json",job["records"])
        buffer = StringIO(newline="")
        writer = csv.DictWriter(buffer,fieldnames=FIELDS,extrasaction="ignore")
        writer.writeheader()
        for row in job["records"]:
            safe = {key: ("'"+value if isinstance(value,str) and value.startswith(("=","+","-","@")) else value)
                    for key,value in row.items()}
            writer.writerow(safe)
        atomic_bytes(folder/"metadata.csv",buffer.getvalue().encode("utf-8-sig"))

    def export_summary(self):
        buffer = StringIO(newline="")
        fields = ["keyword","engine","requested_count","saved_count","original_count","thumbnail_count","status","error"]
        writer = csv.DictWriter(buffer,fieldnames=fields)
        writer.writeheader()
        for job in self.data["jobs"].values():
            saved = self.saved_rows(job)
            row = {field:job.get(field,"") for field in fields}
            row.update(saved_count=len(saved),original_count=sum(r["download_kind"]=="original" for r in saved),
                       thumbnail_count=sum(r["download_kind"]=="thumbnail" for r in saved))
            for key,value in row.items():
                if isinstance(value,str) and value.startswith(("=","+","-","@")):
                    row[key] = "'"+value
            writer.writerow(row)
        atomic_bytes(self.run_dir/"batch_summary.csv",buffer.getvalue().encode("utf-8-sig"))
