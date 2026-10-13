"""Behavioral tests for Korean forms, gallery exports, and real hidden Tk lifecycle."""
import importlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from image_collector.models import Candidate, CollectionOptions, RunResult


def module(name):
    try:
        return importlib.import_module('image_collector.' + name)
    except ImportError as exc:
        raise AssertionError(f'Missing GUI implementation: {exc}') from exc


def form(**changes):
    values = dict(engine='naver', backend='browser', profile='', download_mode='',
                  input_mode='keyword', keyword='고양이', batch_file='', output_root='downloaded_images',
                  limit='3', min_width='', min_height='', min_long_edge='', show_browser=False,
                  period='', usage_rights='')
    values.update(changes)
    return values


class FormTests(unittest.TestCase):
    def test_both_default_modes_are_resolved_per_engine(self):
        snapshot = module('gui').snapshot_form(form(engine='both'))
        self.assertEqual(snapshot.keywords, ('고양이',))
        self.assertEqual(snapshot.options.resolve('naver').download_mode, 'thumbnail')
        self.assertEqual(snapshot.options.resolve('google').download_mode, 'original-only')

    def test_original_mode_with_naver_has_actionable_validation(self):
        for engine in ('naver', 'both'):
            with self.subTest(engine=engine), self.assertRaisesRegex(ValueError, '구글'):
                module('gui').snapshot_form(form(engine=engine, download_mode='original-only'))

    def test_zero_and_non_integer_inputs_rejected_before_work(self):
        for changes in ({'limit': '0'}, {'limit': 'x'}, {'min_width': '0'}, {'min_long_edge': '-1'},
                        {'keyword': '  '}, {'output_root': ''}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                module('gui').snapshot_form(form(**changes))

    def test_size_overrides_and_browser_visibility_captured(self):
        result = module('gui').snapshot_form(form(engine='google', profile='video-landscape',
                    min_width='2000', show_browser=True, period='month', usage_rights='commercial'))
        options = result.options.resolve()
        self.assertEqual((options.min_width, options.min_height, options.min_long_edge), (2000, 1080, 0))
        self.assertFalse(options.headless)
        self.assertEqual((options.period, options.usage_rights), ('month', 'commercial'))

    def test_same_batch_path_is_reloaded_on_every_snapshot(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / 'terms.csv'
            path.write_text('first', encoding='utf-8')
            values = form(input_mode='file', batch_file=str(path))
            loader = lambda path: Path(path).read_text(encoding='utf-8').splitlines()
            first = module('gui').snapshot_form(values, batch_loader=loader)
            path.write_text('second\nthird', encoding='utf-8')
            second = module('gui').snapshot_form(values, batch_loader=loader)
            self.assertEqual(first.keywords, ('first',))
            self.assertEqual(second.keywords, ('second', 'third'))

    def test_preview_requires_single_browser_engine_and_keyword(self):
        for changes in ({'engine': 'both'}, {'engine': 'google', 'backend': 'api'},
                        {'input_mode': 'file', 'batch_file': 'terms.csv'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                module('gui').snapshot_form(form(**changes), preview=True)

    def test_preview_preserves_original_candidate_objects_and_form_snapshot(self):
        gui = module('gui')
        snapshot = gui.snapshot_form(form(engine='google', keyword='first'))
        candidates = (Candidate('https://example.org/thumb', original_url='https://example.org/original', engine='google'),
                      Candidate('https://example.org/other', engine='google'))
        preview = gui.PreviewSnapshot(snapshot, candidates)
        selected = preview.selected([0])
        self.assertIs(selected[0], candidates[0])
        provider = gui.StaticProvider(selected)
        self.assertEqual(tuple(provider.search('first')), (candidates[0],))
        self.assertEqual(preview.form.keywords, ('first',))
        self.assertEqual(selected[0].original_url, 'https://example.org/original')


class GalleryTests(unittest.TestCase):
    def test_source_opener_refuses_non_http_urls(self):
        gallery = module('gallery')
        opened = []
        with patch.object(gallery.webbrowser, 'open', side_effect=lambda value: opened.append(value)):
            for value in ('file:///C:/secret', 'javascript:alert(1)', 'http://', 'https://user:pass@example.org'):
                self.assertFalse(gallery.open_web_url(value))
            self.assertTrue(gallery.open_web_url('https://example.org/source'))
        self.assertEqual(opened, ['https://example.org/source'])

    def test_manifest_only_lists_saved_records_and_contains_paths(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            manifest = {'jobs': {'a': {'folder': 'cat/google', 'records': [
                {'file_name': 'image_001.png', 'status': 'saved', 'width': 1200, 'height': 800,
                 'download_kind': 'original', 'source_url': 'https://example.org'},
                {'file_name': 'failed.png', 'status': 'failed'},
                {'file_name': '../escape.png', 'status': 'saved'}]},
                'b': {'folder': '../outside', 'records': [{'file_name': 'x.png', 'status': 'saved'}]}}}
            items = module('gallery').items_from_manifest(root, manifest)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].path, root / 'cat/google/image_001.png')
            self.assertEqual((items[0].width, items[0].height, items[0].kind), (1200, 800, 'original'))
            self.assertFalse(items[0].path.exists())

    def test_export_never_overwrites_unrelated_or_colliding_files(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            first, second, destination = root / 'one', root / 'two', root / 'out'
            for path in (first, second, destination):
                path.mkdir()
            (first / 'image.png').write_bytes(b'first')
            (second / 'image.png').write_bytes(b'second')
            (destination / 'image.png').write_bytes(b'unrelated')
            exports = module('gallery').export_selection([first / 'image.png', second / 'image.png', root / 'missing'], destination)
            self.assertEqual((destination / 'image.png').read_bytes(), b'unrelated')
            self.assertEqual([path.read_bytes() for path in exports], [b'first', b'second'])
            self.assertEqual(len(set(exports)), 2)


class TkTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.gui = module('gui').CollectorGUI(self.root)
        self.root.update_idletasks()

    def tearDown(self):
        if not self.gui.destroyed:
            self.gui.close()
            self.pump_until(lambda: self.gui.destroyed)

    def pump_until(self, condition, seconds=3):
        end = time.monotonic() + seconds
        while not condition() and time.monotonic() < end:
            self.root.update()
            time.sleep(.01)
        self.assertTrue(condition(), 'Tk worker/event lifecycle did not settle')

    def test_hidden_live_tk_form_builds_and_status_progress_events_display(self):
        self.gui.handle_event({'type': 'log', 'message': '검증 메시지'})
        self.gui.handle_event({'type': 'progress', 'keyword': 'cat', 'engine': 'google', 'saved': 2, 'limit': 3})
        self.assertIn('검증 메시지', self.gui.log_text.get('1.0', 'end'))
        self.assertIn('2/3', self.gui.status_var.get())
        self.assertAlmostEqual(float(self.gui.progress['value']), 200 / 3)

    def test_worker_uses_captured_values_and_only_queues_events(self):
        started, release = threading.Event(), threading.Event()
        observations = []
        def runner(keywords, options, output_root, logger, stop_event, **kwargs):
            started.set()
            release.wait(2)
            observations.append((keywords, options.engine, threading.get_ident()))
            logger({'type': 'log', 'message': 'worker message'})
            return RunResult(Path(output_root) / 'run', [], 'completed')
        self.gui.keyword_var.set('before')
        main_thread = threading.get_ident()
        with patch.object(module('gui'), '_run_collection', runner), patch.object(module('gui'), '_load_run', return_value={'jobs': {}}):
            self.gui.start()
            self.assertTrue(started.wait(1))
            self.gui.keyword_var.set('after')
            release.set()
            self.pump_until(lambda: not self.gui.busy)
        self.assertEqual(observations[0][:2], (('before',), 'naver'))
        self.assertNotEqual(observations[0][2], main_thread)
        self.assertIn('worker message', self.gui.log_text.get('1.0', 'end'))

    def test_close_signals_stop_and_defers_destroy_until_worker_exits(self):
        started = threading.Event()
        def task(stop_event, emit):
            started.set()
            stop_event.wait(2)
            time.sleep(.05)
        self.gui.start_task(task)
        self.assertTrue(started.wait(1))
        self.gui.close()
        self.assertTrue(self.gui.stop_event.is_set())
        self.assertFalse(self.gui.destroyed)
        self.pump_until(lambda: self.gui.destroyed)

    def test_gallery_renders_actual_preview_and_missing_file_message(self):
        from PIL import Image
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            Image.new('RGB', (1200, 800), 'red').save(root / 'valid.png')
            items = module('gallery').items_from_manifest(root, {'jobs': {'a': {'folder': '.', 'records': [
                {'file_name': 'valid.png', 'status': 'saved', 'width': 1200, 'height': 800, 'download_kind': 'original'},
                {'file_name': 'missing.png', 'status': 'saved'}]}}})
            self.gui.gallery.set_items(items)
            self.gui.gallery.show_item(0)
            self.assertIsNotNone(self.gui.gallery.photo)
            self.gui.gallery.show_item(1)
            self.assertIn('없', self.gui.gallery.detail_var.get())


    def test_selected_download_keeps_preview_snapshot_after_form_changes(self):
        gui = module('gui')
        captured = []
        original = Candidate('https://example.org/thumbnail', original_url='https://example.org/full.jpg', engine='google')
        self.gui.preview_snapshot = gui.PreviewSnapshot(gui.snapshot_form(form(engine='google', keyword='before')), (original,))
        self.gui.gallery.set_preview((original,))
        self.gui.keyword_var.set('after')
        self.gui.engine_var.set('네이버')
        def runner(keywords, options, output_root, logger, stop_event, provider_factory, selected_candidates):
            provider = provider_factory('google', options.resolve(), None, stop_event, logger)
            captured.append((keywords, options.engine, tuple(provider.search(keywords[0]))))
            return RunResult(Path(output_root) / 'run', [], 'success')
        with patch.object(gui, '_run_collection', runner), patch.object(gui, '_load_run', return_value={'jobs': {}}):
            self.gui.download_selected([0])
            self.pump_until(lambda: not self.gui.busy)
        self.assertEqual(captured[0][:2], (('before',), 'google'))
        self.assertIs(captured[0][2][0], original)
        self.assertIn('수집 완료', self.gui.status_var.get())

    def test_preview_disables_unsupported_engine_and_backend_with_explanation(self):
        self.gui.engine_var.set('네이버 + 구글')
        self.assertEqual(str(self.gui.preview_button['state']), 'disabled')
        self.assertIn('단일', self.gui.preview_hint_var.get())
        self.gui.engine_var.set('구글')
        self.gui.backend_var.set('외부 검색 API (구글)')
        self.assertEqual(str(self.gui.preview_button['state']), 'disabled')
        self.assertIn('브라우저', self.gui.preview_hint_var.get())

    def test_selected_download_uses_real_runner_and_saved_image_gallery(self):
        import base64
        from io import BytesIO
        from PIL import Image
        gui = module('gui')
        candidates = []
        for color in ('red', 'blue'):
            output = BytesIO()
            Image.new('RGB', (180, 150), color).save(output, format='PNG')
            url = 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
            candidates.append(Candidate(url, title=color, engine='naver'))
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            snapshot = gui.snapshot_form(form(output_root=directory, limit='50'))
            self.gui.preview_snapshot = gui.PreviewSnapshot(snapshot, tuple(candidates))
            self.gui.gallery.set_preview(candidates)
            self.gui.download_selected([0, 1])
            self.pump_until(lambda: not self.gui.busy)
            self.assertIn('수집 완료', self.gui.status_var.get())
            self.assertEqual(len(self.gui.gallery.items), 2)
            self.assertTrue(all(item.path.is_file() for item in self.gui.gallery.items))
            self.gui.gallery.show_item(0)
            self.assertIsNotNone(self.gui.gallery.photo)

    def test_preview_verification_block_has_korean_actionable_status(self):
        from image_collector.models import NeedsAttention
        def task(stop, emit):
            raise NeedsAttention('Search engine verification or traffic block requires user attention.')
        self.gui.start_task(task)
        self.pump_until(lambda: not self.gui.busy)
        self.assertIn('브라우저', self.gui.status_var.get())
        self.assertIn('확인', self.gui.status_var.get())

class PreviewWorkerTests(unittest.TestCase):
    def test_search_preview_bounds_candidates_and_emits_small_real_thumbnails(self):
        import base64
        from io import BytesIO
        from PIL import Image
        from image_collector import providers
        png = BytesIO()
        Image.new('RGB', (640, 480), 'blue').save(png, format='PNG')
        thumbnail = 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode()
        candidates = tuple(Candidate(thumbnail, original_url=f'https://example.org/{index}.jpg', engine='google') for index in range(25))
        closed = []
        class Provider:
            def search(self, keyword):
                self.logger('search detail warning')
                return iter(candidates)
            def close(self):
                closed.append(True)
        def factory(engine, options, browser, stop_event, logger):
            result = Provider()
            result.logger = logger
            return result
        events = []
        snapshot = module('gui').snapshot_form(form(engine='google'))
        with patch.object(providers, 'create_provider', factory):
            result = module('gui').search_preview(snapshot, threading.Event(), events.append)
        self.assertEqual(len(result.candidates), 20)
        self.assertIs(result.candidates[0], candidates[0])
        self.assertTrue(all(isinstance(event, dict) for event in events))
        self.assertEqual([event['message'] for event in events if event['type'] == 'log'], ['search detail warning'])
        thumbs = [event for event in events if event['type'] == 'thumbnail']
        self.assertEqual(len(thumbs), 20)
        with Image.open(BytesIO(thumbs[0]['png_bytes'])) as image:
            self.assertLessEqual(image.width, 180)
            self.assertLessEqual(image.height, 130)
        self.assertTrue(closed)


if __name__ == '__main__':
    unittest.main()
