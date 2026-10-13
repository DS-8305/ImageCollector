import importlib
import tempfile
import threading
import unittest
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from PIL import Image
from image_collector.models import CollectionOptions, Candidate, DownloadedImage, RejectedImage, NeedsAttention
from image_collector.storage import load_run, pixel_hash


class Provider:
    def __init__(self, candidates=(), error=None):
        self.candidates = candidates
        self.error = error
    def search(self, keyword):
        if self.error:
            raise self.error
        yield from self.candidates
    def close(self):
        pass


class Download:
    def __init__(self, options, **kwargs):
        self.options = options
        self.closed = False
    def download(self, candidate, seen_hashes=None):
        if "bad" in candidate.thumbnail_url:
            raise RejectedImage("too small")
        color = "red" if "one" in candidate.thumbnail_url else "blue"
        buffer = BytesIO()
        Image.new("RGBA",(150,150),color).save(buffer,"PNG")
        png = buffer.getvalue()
        return DownloadedImage(png,150,150,pixel_hash(png),candidate.thumbnail_url,"thumbnail")
    def close(self):
        self.closed = True


class RunnerTests(unittest.TestCase):
    def run_api(self):
        try:
            return importlib.import_module("image_collector.runner").run_collection
        except ImportError as exc:
            self.fail(str(exc))

    def factory(self, items=(), error=None):
        return lambda engine, options, browser, **kwargs: Provider(items,error)

    def test_zero_downloads_failed_not_success(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.run_api()(["a"],CollectionOptions(limit=1),root,
                                    provider_factory=self.factory([Candidate("https://test/bad")]),
                                    downloader_factory=Download)
            self.assertEqual((result.status,result.jobs[0].saved_count),("failed",0))
            self.assertEqual(result.jobs[0].status,"failed")

    def test_missing_original_reason_reaches_gui_log_during_collection(self):
        events = []
        candidate = Candidate("https://thumb.example/image.png", engine="google", rank=7)
        with tempfile.TemporaryDirectory() as root:
            result = self.run_api()(["a"], CollectionOptions(engine="google", limit=1), root,
                                    logger=events.append, provider_factory=self.factory([candidate]))
            self.assertEqual(result.saved_count, 0)
            reasons = [event for event in events if event["type"] == "log" and event.get("status") == "skipped"]
            self.assertEqual(len(reasons), 1)
            self.assertEqual((reasons[0]["engine"], reasons[0]["rank"]), ("google", 7))
            self.assertIn("URL", reasons[0]["reason"])
            self.assertIn("원본", reasons[0]["message"])

    def test_partial_count_and_both_engines(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.run_api()(["a"],CollectionOptions(engine="both",limit=2),root,
                                    provider_factory=self.factory([Candidate("https://test/one")]),
                                    downloader_factory=Download)
            self.assertEqual([j.status for j in result.jobs],["partial","partial"])
            self.assertEqual([j.engine for j in result.jobs],["naver","google"])
            self.assertEqual(result.saved_count,2)

    def test_true_empty_distinct_from_provider_failure(self):
        with tempfile.TemporaryDirectory() as root:
            empty = self.run_api()(["a"],CollectionOptions(limit=1),root,
                                    provider_factory=self.factory(),downloader_factory=Download)
            failed = self.run_api()(["a"],CollectionOptions(limit=1),root,
                                    provider_factory=self.factory(error=RuntimeError("selectors changed")),
                                    downloader_factory=Download)
            self.assertEqual(empty.jobs[0].status,"empty")
            self.assertEqual(failed.jobs[0].status,"failed")

    def test_blocked_google_stops_google_but_naver_continues(self):
        def factory(engine, options, browser, **kwargs):
            return Provider(error=NeedsAttention("confirm")) if engine=="google" else Provider([Candidate("https://test/one")])
        with tempfile.TemporaryDirectory() as root:
            result = self.run_api()(["a","b"],CollectionOptions(engine="both",limit=1),root,
                                    provider_factory=factory,downloader_factory=Download)
            self.assertEqual([j.status for j in result.jobs],["success","needs_attention","success","needs_attention"])
            self.assertEqual(result.status,"needs_attention")

    def test_duplicate_keywords_process_once_and_limit_enforced(self):
        with tempfile.TemporaryDirectory() as root:
            result = self.run_api()(["a"," a ",""],CollectionOptions(limit=1),root,
                                    provider_factory=self.factory([Candidate("https://test/one"),Candidate("https://test/two")]),
                                    downloader_factory=Download)
            self.assertEqual(len(result.jobs),1)
            self.assertEqual(result.saved_count,1)
            rows = next(iter(load_run(result.run_dir)["jobs"].values()))["records"]
            self.assertEqual(len([r for r in rows if r["status"]=="saved"]),1)

    def test_cancel_before_start_marks_all_jobs_and_no_browser_work(self):
        stop = threading.Event()
        stop.set()
        def forbidden(*args, **kwargs):
            self.fail("provider created after cancellation")
        with tempfile.TemporaryDirectory() as root:
            result = self.run_api()(["a","b"],CollectionOptions(),root,stop_event=stop,
                                    provider_factory=forbidden,downloader_factory=Download)
            self.assertEqual(result.status,"cancelled")
            self.assertEqual([j.status for j in result.jobs],["cancelled","cancelled"])

    def test_resume_preserves_complete_job_and_retries_partial(self):
        options = CollectionOptions(limit=2)
        with tempfile.TemporaryDirectory() as root:
            first = self.run_api()(["a"],options,root,provider_factory=self.factory([Candidate("https://test/one")]),
                                   downloader_factory=Download)
            second = self.run_api()(["a"],options,root,resume=first.run_dir,
                                    provider_factory=self.factory([Candidate("https://test/one"),Candidate("https://test/two")]),
                                    downloader_factory=Download)
            self.assertEqual(first.run_dir,second.run_dir)
            self.assertEqual(second.saved_count,2)
            self.assertEqual(second.status,"success")
            third = self.run_api()(["a"],options,root,resume=first.run_dir,
                                   provider_factory=lambda *a,**k:self.fail("complete jobs rerun"),
                                   downloader_factory=Download)
            self.assertEqual(third.saved_count,2)

    def test_incompatible_resume_rejected_without_changing_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            first = self.run_api()(["a"],CollectionOptions(limit=1),root,
                                   provider_factory=self.factory(),downloader_factory=Download)
            path = first.run_dir/"run.json"
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                self.run_api()(["a"],CollectionOptions(limit=2),root,resume=first.run_dir,
                                provider_factory=self.factory(),downloader_factory=Download)
            self.assertEqual(path.read_bytes(),before)


    def test_selected_candidates_persist_and_resume_never_searches_unselected(self):
        class Failure(Download):
            def download(self, candidate, seen_hashes=None):
                raise RejectedImage("temporary failure")
        options=CollectionOptions(limit=1)
        selected=Candidate("https://test/one",source_url="https://source/selected")
        with tempfile.TemporaryDirectory() as root:
            try:
                first=self.run_api()(["a"],options,root,selected_candidates=[selected],
                                     downloader_factory=Failure)
            except TypeError as exc:
                self.fail(f"Selection persistence API missing: {exc}")
            self.assertEqual(first.status,"failed")
            def forbidden(*a,**k):
                self.fail("Resume searched for new unselected images")
            second=self.run_api()(["a"],options,root,resume=first.run_dir,
                                  provider_factory=forbidden,downloader_factory=Download)
            job=next(iter(load_run(second.run_dir)["jobs"].values()))
            saved=[row for row in job["records"] if row["status"]=="saved"]
            self.assertEqual([row["source_url"] for row in saved],["https://source/selected"])
            self.assertEqual(second.saved_count,1)


    def test_candidate_errors_and_events_do_not_lose_valid_outputs(self):
        messages=[]
        with tempfile.TemporaryDirectory() as root:
            result = self.run_api()(["a"],CollectionOptions(limit=1),root,logger=messages.append,
                                    provider_factory=self.factory([Candidate("https://test/bad"),Candidate("https://test/one")]),
                                    downloader_factory=Download)
            self.assertEqual(result.status,"success")
            self.assertTrue(any(e["type"]=="progress" and e["saved"]==1 for e in messages))
            self.assertTrue((result.run_dir/"batch_summary.csv").is_file())
            job = next(iter(load_run(result.run_dir)["jobs"].values()))
            self.assertEqual([r["status"] for r in job["records"]],["skipped","saved"])
