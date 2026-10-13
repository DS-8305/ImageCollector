import importlib
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from io import BytesIO
from PIL import Image
from image_collector.models import CollectionOptions, Candidate, DownloadedImage


class StorageTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module("image_collector.storage")
        except ImportError as exc:
            self.fail(str(exc))

    def test_keyword_paths_dont_collide_or_use_windows_devices(self):
        m = self.module()
        names = [m.safe_keyword_name(s) for s in ("a/b", "a b", "CON", "con", "a"*200, "a"*201)]
        self.assertEqual(len(set(names)), 6)
        self.assertTrue(all(name.startswith("kw_") and len(name) < 100 for name in names))

    def test_previous_output_preserved_and_runs_distinct(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            previous = Path(root) / "old" / "image_01.png"
            previous.parent.mkdir()
            previous.write_bytes(b"old")
            a = m.RunStore.create(["a"], CollectionOptions(), root)
            a.close()
            b = m.RunStore.create(["a"], CollectionOptions(), root)
            b.close()
            self.assertNotEqual(a.run_dir, b.run_dir)
            self.assertEqual(previous.read_bytes(), b"old")
            self.assertEqual(len(m.load_run(a.run_dir)["jobs"]), 1)

    def test_pending_image_recovery_and_missing_file_reclassification(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            store = m.RunStore.create(["a"], CollectionOptions(), root)
            job = next(iter(store.data["jobs"].values()))
            buffer = BytesIO()
            Image.new("RGBA", (150,150), "red").save(buffer, "PNG")
            payload = buffer.getvalue()
            image = DownloadedImage(payload,150,150,m.pixel_hash(payload),"https://example.com/a","thumbnail")
            row = store.begin_image(job, Candidate("https://example.com/a"), image)
            image_path = store.job_folder(job) / row["file_name"]
            m.atomic_bytes(image_path, payload)  # crash boundary before commit_image
            store.close()
            reopened = m.RunStore.open(store.run_dir)
            restored_job = next(iter(reopened.data["jobs"].values()))
            self.assertEqual(restored_job["records"][0]["status"], "saved")
            image_path.unlink()
            reopened.close()
            missing = m.RunStore.open(store.run_dir)
            self.assertEqual(next(iter(missing.data["jobs"].values()))["records"][0]["status"], "failed")
            missing.close()

    def test_manifest_path_escape_rejected(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            store = m.RunStore.create(["a"], CollectionOptions(), root)
            job = next(iter(store.data["jobs"].values()))
            job["folder"] = "../escape"
            store.checkpoint()
            store.close()
            with self.assertRaises(ValueError):
                m.load_run(store.run_dir)

    def test_exclusive_run_lock(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            store = m.RunStore.create(["a"], CollectionOptions(), root)
            try:
                with self.assertRaises(RuntimeError):
                    m.RunStore.open(store.run_dir)
            finally:
                store.close()
            reopened = m.RunStore.open(store.run_dir)
            reopened.close()


    def test_atomic_replace_retries_transient_windows_sharing_errors(self):
        m=self.module()
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"state.json"
            path.write_bytes(b"old")
            real=m.os.replace
            attempts=[]
            def sharing(source,target):
                attempts.append(1)
                if len(attempts)<3:
                    error=PermissionError(13,"busy")
                    error.winerror=32
                    raise error
                return real(source,target)
            with patch.object(m.os,"replace",side_effect=sharing):
                try:
                    m.atomic_bytes(path,b"new")
                except PermissionError:
                    self.fail("Transient file sharing error was not retried")
            self.assertEqual(path.read_bytes(),b"new")
            self.assertEqual(list(Path(root).glob("*.part")),[])



    def test_new_image_names_preserve_unknown_and_corrupted_prior_files(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as root:
            store=m.RunStore.create(["a"],CollectionOptions(),root)
            job=next(iter(store.data["jobs"].values()))
            folder=store.job_folder(job)
            folder.mkdir(parents=True)
            unknown=folder/"image_01.png"
            unknown.write_bytes(b"user file")
            buffer=BytesIO()
            Image.new("RGBA",(150,150),"red").save(buffer,"PNG")
            png=buffer.getvalue()
            payload=DownloadedImage(png,150,150,m.pixel_hash(png),"https://test/one","thumbnail")
            row=store.begin_image(job,Candidate("https://test/one"),payload)
            self.assertNotEqual(row["file_name"],"image_01.png")
            store.commit_image(job,row,payload)
            self.assertEqual(unknown.read_bytes(),b"user file")
            corrupted=folder/row["file_name"]
            corrupted.write_bytes(b"corrupted previous image")
            store.close()
            store=m.RunStore.open(store.run_dir)
            job=next(iter(store.data["jobs"].values()))
            next_row=store.begin_image(job,Candidate("https://test/two"),payload)
            store.commit_image(job,next_row,payload)
            self.assertEqual(corrupted.read_bytes(),b"corrupted previous image")
            store.close()



    def test_stale_lock_race_never_grants_two_owners(self):
        m=self.module()
        import threading, socket
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            original=m.RunStore.create(["a"],CollectionOptions(),root)
            original.close()
            (original.run_dir/"run.lock").write_text(json.dumps({"pid":0,"host":socket.gethostname()}))
            first_checked=threading.Event()
            release_first=threading.Event()
            release_owners=threading.Event()
            second_done=threading.Event()
            owners=[]
            errors=[]
            def old_owner_check(pid):
                if threading.current_thread().name=="first":
                    first_checked.set()
                    release_first.wait(2)
                return False
            def acquire():
                try:
                    owner=m.RunStore.open(original.run_dir)
                    owners.append(threading.current_thread().name)
                    if threading.current_thread().name=="second":
                        second_done.set()
                    release_owners.wait(2)
                    owner.close()
                except RuntimeError:
                    second_done.set()
                except Exception as exc:
                    errors.append(exc)
                    second_done.set()
            with patch.object(m,"_process_alive",side_effect=old_owner_check,create=True):
                first=threading.Thread(target=acquire,name="first")
                first.start()
                first_checked.wait(.3)
                second=threading.Thread(target=acquire,name="second")
                second.start()
                second_done.wait(1)
                release_first.set()
                first.join(.3)
                release_owners.set()
                first.join(3)
                second.join(3)
            self.assertEqual(errors,[])
            self.assertEqual(len(owners),1,owners)


class BatchInputTests(unittest.TestCase):
    def module(self):
        try:
            return importlib.import_module("image_collector.batch_input")
        except ImportError as exc:
            self.fail(str(exc))

    def test_changed_file_is_read_fresh(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"a.csv"
            path.write_text("keyword\\nfirst\\n".replace("\\n","\n"), encoding="utf-8")
            self.assertEqual(m.load_keywords(path), ["first"])
            path.write_text("keyword\nsecond\nsecond\n", encoding="cp949")
            self.assertEqual(m.load_keywords(path), ["second"])

    def test_xlsx_header_column_and_order(self):
        m = self.module()
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"a.xlsx"
            wb = Workbook()
            wb.active.append(["other","keyword"])
            wb.active.append(["x","수면안대"])
            wb.active.append(["x",""])
            wb.active.append(["x","수면안대"])
            wb.active.append(["x","핸드크림"])
            wb.save(path)
            wb.close()
            self.assertEqual(m.load_keywords(path), ["수면안대","핸드크림"])
