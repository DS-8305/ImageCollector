import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import naver_image_collector as legacy
from image_collector.models import RunResult, JobResult


class CompatibilityTests(unittest.TestCase):
    def test_old_collection_call_uses_preserving_run_store(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"run_new"/"kw_a"/"naver"/"image_01.png"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"fixture")
            result=RunResult(Path(root)/"run_new",[JobResult("a","naver",1,"success",folder="kw_a/naver")],"success")
            with patch("image_collector.runner.run_collection",return_value=result),patch.object(legacy.NaverImageCollector,"_build_driver",side_effect=AssertionError("old browser path")):
                self.assertEqual(legacy.collect_single_keyword("a",limit=1),[path])

    def test_legacy_batch_zero_not_success(self):
        result=legacy.run_batch_collection(["a"],limit=1,logger=lambda x:None,
                                            collector_func=lambda *a:[])
        self.assertEqual(result[0].status,"failed")
