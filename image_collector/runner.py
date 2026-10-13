"""Sequential jobs, cancellation, explicit resume and structured progress events."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

from .models import (Candidate, CollectionOptions, RunResult, JobResult, CollectionError,
                     Cancelled, NeedsAttention, RejectedImage, DuplicateImage)
from .storage import RunStore, load_run


def _status(jobs):
    states = {job.status for job in jobs}
    for state in ("cancelled","needs_attention","failed","partial"):
        if state in states:
            return state
    return "success" if "success" in states else "empty"


def _result(store, job):
    saved = store.saved_rows(job)
    return JobResult(job["keyword"],job["engine"],len(saved),job["status"],job.get("error",""),
                     job["requested_count"],sum(r["download_kind"]=="original" for r in saved),
                     sum(r["download_kind"]=="thumbnail" for r in saved),job["folder"])


def run_collection(keywords, options: CollectionOptions, output_root="downloaded_images",
                   logger=None, stop_event=None, resume=None, retry_failed=False,
                   provider_factory=None, downloader_factory=None, selected_candidates=None) -> RunResult:
    from .browser import BrowserSession
    from .providers import create_provider
    from .downloader import Downloader

    keywords = list(dict.fromkeys(k.strip() for k in keywords if k.strip()))
    if not keywords:
        raise ValueError("검색어를 입력하세요.")
    resolved = {engine: options.resolve(engine) for engine in options.engines}
    if retry_failed and not resume:
        raise ValueError("실패 재실행에는 기존 실행 폴더가 필요합니다.")
    if selected_candidates is not None:
        selected_candidates = tuple(selected_candidates)
        if (resume or len(keywords) != 1 or len(options.engines) != 1 or not selected_candidates
                or not all(isinstance(c,Candidate) for c in selected_candidates)):
            raise ValueError("선택 다운로드는 새 실행의 단일 검색어·단일 엔진 후보에만 적용할 수 있습니다.")
    existing = load_run(resume) if resume else None
    needs_search = selected_candidates is None and not (existing and all(
        j.get("selected_candidates") for j in existing["jobs"].values()))
    if needs_search and provider_factory is None and options.backend == "api" and not os.environ.get("SERPAPI_API_KEY"):
        raise ValueError("외부 API를 사용하려면 SERPAPI_API_KEY 환경 변수를 설정하세요.")
    if resume:
        if existing["keywords"] != keywords or existing["options"] != asdict(options):
            raise ValueError("이어받기 검색어와 수집 설정이 기존 실행과 다릅니다.")
        store = RunStore.open(resume)
    else:
        store = RunStore.create(keywords,options,output_root,selected_candidates=selected_candidates)
    stop = stop_event if stop_event is not None else threading.Event()
    headless = all(item.headless for item in resolved.values())
    browser = BrowserSession(headless=headless)
    supply = provider_factory or create_provider
    download_type = downloader_factory or Downloader
    blocked = {}

    def emit(kind, **data):
        if logger:
            logger({"type":kind,**data})

    def provider_log(message):
        emit("log",message=str(message))

    emit("run",path=str(store.run_dir),run_id=store.data["run_id"])
    try:
        for job in store.data["jobs"].values():
            saved = store.saved_rows(job)
            if job["status"] == "success" and len(saved) >= job["requested_count"]:
                emit("job",result=asdict(_result(store,job)))
                continue
            if job["status"] == "empty":
                emit("job",result=asdict(_result(store,job)))
                continue
            if stop.is_set():
                job.update(status="cancelled",error="사용자가 중단했습니다.")
                store.checkpoint()
                store.export_job(job)
                emit("job",result=asdict(_result(store,job)))
                continue
            if job["engine"] in blocked:
                job.update(status="needs_attention",error=blocked[job["engine"]])
                store.checkpoint()
                store.export_job(job)
                emit("job",result=asdict(_result(store,job)))
                continue
            if retry_failed and job["status"] not in ("failed","partial","needs_attention","cancelled"):
                continue
            item_options = resolved[job["engine"]]
            job.update(status="running",error="")
            store.checkpoint()
            emit("log",message=f'{job["engine"]} / {job["keyword"]} 수집 시작')
            deadline = time.monotonic() + item_options.keyword_timeout
            provider = download = iterator = None
            seen_ids = {row["candidate_id"] for row in saved}
            seen_hashes = {row["content_hash"] for row in saved}
            received = 0
            try:
                if job.get("selected_candidates"):
                    selected = [Candidate(**row) for row in job["selected_candidates"]]
                    class SelectionProvider:
                        def search(self, keyword):
                            return iter(selected)
                    provider = SelectionProvider()
                else:
                    provider = supply(job["engine"],item_options,browser,stop_event=stop,logger=provider_log)
                download = download_type(item_options,stop_event=stop,deadline=deadline)
                iterator = iter(provider.search(job["keyword"]))
                for candidate in iterator:
                    if stop.is_set():
                        raise Cancelled("사용자가 중단했습니다.")
                    received += 1
                    if time.monotonic() >= deadline:
                        job["error"] = "키워드 작업 제한 시간에 도달했습니다."
                        break
                    if received > item_options.max_candidates:
                        job["error"] = "후보 제한에 도달했습니다."
                        break
                    if not isinstance(candidate,Candidate):
                        raise CollectionError("수집기가 올바르지 않은 이미지 후보를 반환했습니다.")
                    candidate = replace(candidate,engine=job["engine"],rank=candidate.rank or received)
                    if candidate.candidate_id in seen_ids:
                        continue
                    seen_ids.add(candidate.candidate_id)
                    if len(store.saved_rows(job)) >= item_options.limit:
                        break
                    try:
                        image = download.download(candidate,seen_hashes=seen_hashes)
                    except DuplicateImage as exc:
                        store.record_error(job,candidate,"duplicate",exc)
                        continue
                    except RejectedImage as exc:
                        store.record_error(job,candidate,"skipped",exc)
                        continue
                    except (Cancelled, NeedsAttention):
                        raise
                    except Exception as exc:
                        store.record_error(job,candidate,"failed",exc)
                        continue
                    # Persist intent before the file so an interrupted commit can be recovered.
                    row = store.begin_image(job,candidate,image)
                    store.commit_image(job,row,image)
                    seen_hashes.add(image.content_hash)
                    count = len(store.saved_rows(job))
                    emit("progress",keyword=job["keyword"],engine=job["engine"],saved=count,limit=item_options.limit)
                    if count >= item_options.limit:
                        break
                count = len(store.saved_rows(job))
                if count >= item_options.limit:
                    job["status"] = "success"
                elif count:
                    job["status"] = "partial"
                    job["error"] = job["error"] or "조건을 만족하는 이미지가 요청 수보다 적습니다."
                elif received:
                    job["status"] = "failed"
                    job["error"] = job["error"] or "저장 조건을 만족한 이미지가 없습니다. 이미지 기록의 사유를 확인하세요."
                else:
                    job["status"] = "empty"
                    job["error"] = ""
            except Cancelled as exc:
                stop.set()
                job.update(status="cancelled",error=str(exc))
            except NeedsAttention as exc:
                blocked[job["engine"]] = str(exc)
                job.update(status="needs_attention",error=str(exc))
            except Exception as exc:
                job.update(status="failed",error=str(exc))
            finally:
                for resource in (iterator,download,provider):
                    close = getattr(resource,"close",None)
                    if close:
                        try:
                            close()
                        except Exception as exc:
                            emit("log",message=f"리소스 정리: {exc}")
                store.checkpoint()
                store.export_job(job)
            emit("job",result=asdict(_result(store,job)))
        jobs = [_result(store,job) for job in store.data["jobs"].values()]
        status = _status(jobs)
        store.data["status"] = status
        store.checkpoint()
        store.export_summary()
        return RunResult(store.run_dir,jobs,status)
    finally:
        try:
            browser.close()
        finally:
            store.close()
