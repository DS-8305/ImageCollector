import contextlib
import importlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from image_collector.models import CollectionOptions, RunResult, JobResult
from image_collector.storage import RunStore


class CliTests(unittest.TestCase):
    def cli(self):
        try:
            return importlib.import_module("image_collector.cli")
        except ImportError as exc:
            self.fail(str(exc))

    def test_google_default_options_reach_runner(self):
        cli=self.cli()
        result=RunResult(Path("output"),[JobResult("a","google",0,"empty")],"empty")
        captured=[]
        def run(keys,options,**kwargs):
            captured.append((keys,options))
            return result
        with patch.object(cli,"run_collection",side_effect=run),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--keyword","a","--engine","google"]),0)
        self.assertEqual(captured[0][1].resolve().download_mode,"original-only")

    def test_failure_and_cancel_return_nonzero(self):
        cli=self.cli()
        for state,want in [("failed",1),("needs_attention",1),("cancelled",130),("partial",0)]:
            with patch.object(cli,"run_collection",return_value=RunResult(Path("x"),[],state)),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["--keyword","a"]),want)

    def test_resume_loads_saved_options_without_default_overrides(self):
        cli=self.cli()
        with tempfile.TemporaryDirectory() as root:
            store=RunStore.create(["a"],CollectionOptions(engine="google",limit=7),root)
            store.close()
            captured=[]
            def run(keys,options,**kwargs):
                captured.append((keys,options,kwargs))
                return RunResult(store.run_dir,[],"empty")
            with patch.object(cli,"run_collection",side_effect=run),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["--resume",str(store.run_dir),"--retry-failed"]),0)
            self.assertEqual((captured[0][1].engine,captured[0][1].limit),("google",7))
            self.assertTrue(captured[0][2]["retry_failed"])

    def test_invalid_original_naver_stops_before_runner(self):
        cli=self.cli()
        with patch.object(cli,"run_collection",side_effect=AssertionError("should not run")),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["--keyword","a","--download-mode","original-only"]),2)

    def test_batch_encoding_and_both_cli(self):
        cli=self.cli()
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"a.csv"
            path.write_text("keyword\n수면안대\n수면안대\n핸드크림\n",encoding="cp949")
            captured=[]
            def run(keys,options,**kwargs):
                captured.append((keys,options))
                return RunResult(Path(root),[],"empty")
            with patch.object(cli,"run_collection",side_effect=run),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["--batch-file",str(path),"--engine","both"]),0)
            self.assertEqual(captured[0][0],["수면안대","핸드크림"])
            self.assertEqual(captured[0][1].engines,("naver","google"))
