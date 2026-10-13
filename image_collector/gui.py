"""Korean Tk GUI. Worker threads operate on immutable snapshots and queues only."""
from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .gallery import Gallery, items_from_manifest
from .models import Cancelled, Candidate, CollectionOptions, NeedsAttention


@dataclass(frozen=True)
class FormSnapshot:
    keywords: tuple[str, ...]
    options: CollectionOptions
    output_root: Path


@dataclass(frozen=True)
class PreviewSnapshot:
    form: FormSnapshot
    candidates: tuple[Candidate, ...]

    def selected(self, indices):
        chosen = set(indices)
        return tuple(candidate for index, candidate in enumerate(self.candidates) if index in chosen)


class StaticProvider:
    def __init__(self, candidates):
        self.candidates = tuple(candidates)

    def search(self, keyword):
        return iter(self.candidates)

    def close(self):
        pass


def _load_keywords(path):
    from .batch_input import load_keywords
    return load_keywords(path)


def _run_collection(*args, **kwargs):
    from .runner import run_collection
    return run_collection(*args, **kwargs)


def _load_run(path):
    from .runner import load_run
    return load_run(path)


def snapshot_form(values, batch_loader=None, preview=False):
    """Validate fresh input each time, before a worker or any network operation."""
    def number(name, label, optional=False):
        value = str(values.get(name, '')).strip()
        if not value and optional:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(label + '에는 정수를 입력하세요.') from exc

    engine = values.get('engine', 'naver')
    backend = values.get('backend', 'browser')
    if preview and (engine == 'both' or backend != 'browser' or values.get('input_mode') == 'file'):
        raise ValueError('검색 미리보기는 단일 검색어와 네이버 또는 구글의 브라우저 방식에서 사용할 수 있습니다.')
    mode = values.get('download_mode') or None
    if engine in ('naver', 'both') and mode in ('original-only', 'original-preferred'):
        raise ValueError('원본 저장은 구글을 선택하세요. 네이버/통합 검색은 엔진 기본값 또는 썸네일 저장을 사용하세요.')
    visibility = values.get('show_browser')
    options = CollectionOptions(engine=engine, backend=backend, profile=values.get('profile') or None,
            download_mode=mode, limit=number('limit', '저장 수'),
            min_width=number('min_width', '최소 가로', True), min_height=number('min_height', '최소 세로', True),
            min_long_edge=number('min_long_edge', '최소 긴 변', True),
            headless=None if visibility is None else not bool(visibility),
            period=values.get('period') or '', usage_rights=values.get('usage_rights') or '')
    for chosen_engine in options.engines:
        options.resolve(chosen_engine)
    if values.get('input_mode') == 'file':
        path = str(values.get('batch_file', '')).strip()
        if not path:
            raise ValueError('CSV 또는 XLSX 검색어 파일을 선택하세요.')
        keywords = tuple((batch_loader or _load_keywords)(path))
        if not keywords:
            raise ValueError('파일에 유효한 검색어가 없습니다.')
    else:
        keyword = str(values.get('keyword', '')).strip()
        if not keyword:
            raise ValueError('검색어를 입력하세요.')
        keywords = (keyword,)
    output = str(values.get('output_root', '')).strip()
    if not output:
        raise ValueError('이미지를 저장할 폴더를 선택하세요.')
    return FormSnapshot(keywords, options, Path(output))


def search_preview(snapshot, stop_event, emit):
    """Search at most twenty candidates, then fetch small thumbnails off Tk's thread."""
    from .browser import BrowserSession
    from .providers import create_provider
    from .downloader import Downloader
    from PIL import Image
    resolved = snapshot.options.resolve()
    browser = BrowserSession(headless=resolved.headless)
    provider = None
    downloader = None
    try:
        provider = create_provider(resolved.engine, resolved, browser, stop_event,
                                   lambda message: emit({'type': 'log', 'message': str(message)}))
        candidates = []
        for candidate in provider.search(snapshot.keywords[0]):
            if stop_event.is_set():
                raise Cancelled('미리보기를 중단했습니다.')
            candidates.append(candidate)
            if len(candidates) >= 20:
                break
        preview = PreviewSnapshot(snapshot, tuple(candidates))
        emit({'type': 'preview', 'preview': preview})
        thumbnail_options = CollectionOptions(engine=resolved.engine, download_mode='thumbnail', profile='custom',
            min_width=1, min_height=1, min_long_edge=0).resolve()
        # Individual network calls are bounded by downloader; the whole preview has a deadline.
        downloader = Downloader(thumbnail_options, stop_event=stop_event, deadline=time.monotonic() + 90)
        for index, candidate in enumerate(candidates):
            if stop_event.is_set():
                raise Cancelled('미리보기를 중단했습니다.')
            try:
                downloaded = downloader.download(candidate)
                with Image.open(BytesIO(downloaded.png_bytes)) as image:
                    image.thumbnail((180, 130))
                    output = BytesIO()
                    image.save(output, format='PNG')
                emit({'type': 'thumbnail', 'index': index, 'png_bytes': output.getvalue()})
            except Cancelled:
                raise
            except Exception as exc:
                emit({'type': 'thumbnail', 'index': index, 'error': str(exc)})
        return preview
    finally:
        if downloader:
            downloader.close()
        try:
            if provider:
                provider.close()
        finally:
            browser.close()


ENGINE = {'네이버': 'naver', '구글': 'google', '네이버 + 구글': 'both'}
BACKEND = {'브라우저 (무료)': 'browser', '외부 검색 API (구글)': 'api'}
PROFILE = {'엔진 기본값': '', '썸네일 (150px)': 'legacy-thumbnail', '블로그 (긴 변 1200px)': 'blog',
           '가로 영상 (1920×1080)': 'video-landscape', '세로 영상 (1080×1920)': 'video-portrait', '직접 지정': 'custom'}
MODE = {'엔진 기본값': '', '썸네일': 'thumbnail', '원본만': 'original-only', '원본 우선 (실패 시 썸네일)': 'original-preferred'}
PERIOD = {'전체 기간': '', '지난 하루': 'day', '지난 일주일': 'week', '지난 한 달': 'month', '지난 일 년': 'year'}
RIGHTS = {'필터 없음': '', '크리에이티브 커먼즈': 'creative-commons', '상업용 및 기타 라이선스': 'commercial'}


class CollectorGUI:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.worker = None
        self.stop_event = threading.Event()
        self.busy = False
        self.closing = False
        self.destroyed = False
        self.after_id = None
        self.preview_snapshot = None
        self.last_run_dir = None
        root.title(f'이미지 수집기 {__version__} · 네이버 / 구글')
        root.geometry('1120x860')
        root.minsize(850, 650)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.engine_var = tk.StringVar(value='네이버')
        self.backend_var = tk.StringVar(value='브라우저 (무료)')
        self.profile_var = tk.StringVar(value='엔진 기본값')
        self.mode_var = tk.StringVar(value='엔진 기본값')
        self.keyword_var = tk.StringVar()
        self.input_mode_var = tk.StringVar(value='keyword')
        self.batch_file_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(Path.cwd() / 'downloaded_images'))
        self.limit_var = tk.StringVar(value='50')
        self.min_width_var = tk.StringVar()
        self.min_height_var = tk.StringVar()
        self.min_long_edge_var = tk.StringVar()
        self.show_browser_var = tk.BooleanVar(value=False)
        self.period_var = tk.StringVar(value='전체 기간')
        self.rights_var = tk.StringVar(value='필터 없음')
        self.resume_var = tk.StringVar()
        self.status_var = tk.StringVar(value='검색어와 저장 기준을 선택하세요.')
        self.preview_hint_var = tk.StringVar(value='검색 미리보기: 단일 검색어 · 단일 엔진 · 브라우저 방식')
        frame = ttk.Frame(root, padding=12)
        frame.pack(fill='both', expand=True)
        form = ttk.LabelFrame(frame, text='수집 설정', padding=10)
        form.pack(fill='x')
        for column in (1, 3, 5, 7):
            form.columnconfigure(column, weight=1)
        self.form_widgets = []
        for column, title, variable, mapping in [(0, '검색엔진', self.engine_var, ENGINE),
                (2, '수집 방식', self.backend_var, BACKEND), (4, '크기 프리셋', self.profile_var, PROFILE),
                (6, '저장 방식', self.mode_var, MODE)]:
            ttk.Label(form, text=title).grid(row=0, column=column, sticky='w', padx=3)
            box = ttk.Combobox(form, textvariable=variable, values=tuple(mapping), state='readonly', width=20)
            box.grid(row=0, column=column + 1, sticky='ew', padx=3, pady=3)
            self.form_widgets.append((box, 'readonly'))
        self.engine_var.trace_add('write', self._engine_changed)
        keyword_radio = ttk.Radiobutton(form, text='검색어', variable=self.input_mode_var, value='keyword')
        keyword_radio.grid(row=1, column=0, sticky='w', pady=4)
        keyword_entry = ttk.Entry(form, textvariable=self.keyword_var)
        keyword_entry.grid(row=1, column=1, columnspan=7, sticky='ew', padx=3)
        file_radio = ttk.Radiobutton(form, text='검색어 파일', variable=self.input_mode_var, value='file')
        file_radio.grid(row=2, column=0, sticky='w')
        file_entry = ttk.Entry(form, textvariable=self.batch_file_var)
        file_entry.grid(row=2, column=1, columnspan=6, sticky='ew', padx=3)
        file_button = ttk.Button(form, text='CSV / XLSX 선택', command=self.choose_batch)
        file_button.grid(row=2, column=7, sticky='ew', padx=3)
        ttk.Label(form, text='저장 폴더').grid(row=3, column=0, sticky='w', pady=4)
        output_entry = ttk.Entry(form, textvariable=self.output_var)
        output_entry.grid(row=3, column=1, columnspan=6, sticky='ew', padx=3)
        output_button = ttk.Button(form, text='폴더 선택', command=self.choose_output)
        output_button.grid(row=3, column=7, sticky='ew', padx=3)
        for column, label, variable in [(0, '검색어별 저장 수', self.limit_var), (2, '최소 가로', self.min_width_var),
                (4, '최소 세로', self.min_height_var), (6, '최소 긴 변', self.min_long_edge_var)]:
            ttk.Label(form, text=label).grid(row=4, column=column, sticky='w', pady=3)
            entry = ttk.Entry(form, textvariable=variable, width=10)
            entry.grid(row=4, column=column + 1, sticky='ew', padx=3)
            self.form_widgets.append((entry, 'normal'))
        show = ttk.Checkbutton(form, text='브라우저 표시 (동의·차단 화면 확인)', variable=self.show_browser_var)
        show.grid(row=5, column=0, columnspan=3, sticky='w', pady=4)
        ttk.Label(form, text='구글 검색 기간').grid(row=5, column=3, sticky='w')
        period = ttk.Combobox(form, textvariable=self.period_var, values=tuple(PERIOD), state='readonly', width=14)
        period.grid(row=5, column=4, sticky='ew', padx=3)
        ttk.Label(form, text='구글 사용 권한').grid(row=5, column=5, sticky='w')
        rights = ttk.Combobox(form, textvariable=self.rights_var, values=tuple(RIGHTS), state='readonly', width=23)
        rights.grid(row=5, column=6, columnspan=2, sticky='ew', padx=3)
        ttk.Label(form, text='크기는 빈칸이면 프리셋 적용 · 엔진 기본값: 네이버 썸네일 / 구글 원본 · 사용 권한은 출처에서 확인하세요.',
                  wraplength=1000).grid(row=6, column=0, columnspan=8, sticky='w', pady=(3, 0))
        for widget in (keyword_radio, keyword_entry, file_radio, file_entry, file_button, output_entry, output_button, show):
            self.form_widgets.append((widget, 'normal'))
        self.form_widgets.extend([(period, 'readonly'), (rights, 'readonly')])
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=8)
        self.start_button = ttk.Button(actions, text='수집 시작', command=self.start)
        self.start_button.pack(side='left')
        self.preview_button = ttk.Button(actions, text='검색 미리보기 (최대 20개)', command=self.preview)
        self.preview_button.pack(side='left', padx=6)
        self.stop_button = ttk.Button(actions, text='중단', command=self.stop, state='disabled')
        self.stop_button.pack(side='left')
        ttk.Label(actions, text='  실행 폴더').pack(side='left', padx=(10, 3))
        self.resume_entry = ttk.Entry(actions, textvariable=self.resume_var, width=25)
        self.resume_entry.pack(side='left', fill='x', expand=True)
        self.resume_picker = ttk.Button(actions, text='선택', command=self.choose_resume)
        self.resume_picker.pack(side='left', padx=3)
        self.resume_button = ttk.Button(actions, text='이어받기', command=self.resume)
        self.resume_button.pack(side='left')
        self.retry_button = ttk.Button(actions, text='실패 재시도', command=lambda: self.resume(True))
        self.retry_button.pack(side='left', padx=3)
        self.results_button = ttk.Button(actions, text='결과 열기', command=self.open_results)
        self.results_button.pack(side='left')
        ttk.Label(frame, textvariable=self.preview_hint_var).pack(fill='x', pady=(0, 5))
        self.backend_var.trace_add('write', self._update_preview_availability)
        self.input_mode_var.trace_add('write', self._update_preview_availability)
        self.gallery = Gallery(frame, on_download=self.download_selected)
        self.gallery.pack(fill='both', expand=True)
        self.progress = ttk.Progressbar(frame, maximum=100, mode='determinate')
        self.progress.pack(fill='x', pady=(8, 3))
        ttk.Label(frame, textvariable=self.status_var, wraplength=1000).pack(fill='x')
        logs = ttk.LabelFrame(frame, text='진행 로그', padding=4)
        logs.pack(fill='x', pady=(6, 0))
        self.log_text = tk.Text(logs, height=6, wrap='word', state='disabled')
        self.log_text.pack(fill='both', expand=True)
        self.after_id = root.after(80, self._pump)

    def _engine_changed(self, *_):
        engine = ENGINE.get(self.engine_var.get(), self.engine_var.get())
        self.show_browser_var.set(engine in ('google', 'both'))
        self._update_preview_availability()

    def _update_preview_availability(self, *_):
        engine = ENGINE.get(self.engine_var.get(), self.engine_var.get())
        backend = BACKEND.get(self.backend_var.get(), self.backend_var.get())
        supported = engine != 'both' and backend == 'browser' and self.input_mode_var.get() == 'keyword'
        self.preview_button.configure(state='normal' if supported and not self.busy else 'disabled')
        self.preview_hint_var.set('검색 미리보기: 단일 검색어 · 단일 엔진 · 브라우저 방식' if supported else
                                 '검색 미리보기는 단일 검색어, 네이버 또는 구글 단일 엔진, 브라우저 방식에서 지원합니다.')

    def _form_values(self):
        return {'engine': ENGINE.get(self.engine_var.get(), self.engine_var.get()),
                'backend': BACKEND.get(self.backend_var.get(), self.backend_var.get()),
                'profile': PROFILE.get(self.profile_var.get(), self.profile_var.get()),
                'download_mode': MODE.get(self.mode_var.get(), self.mode_var.get()),
                'input_mode': self.input_mode_var.get(), 'keyword': self.keyword_var.get(),
                'batch_file': self.batch_file_var.get(), 'output_root': self.output_var.get(),
                'limit': self.limit_var.get(), 'min_width': self.min_width_var.get(),
                'min_height': self.min_height_var.get(), 'min_long_edge': self.min_long_edge_var.get(),
                'show_browser': self.show_browser_var.get(), 'period': PERIOD.get(self.period_var.get(), self.period_var.get()),
                'usage_rights': RIGHTS.get(self.rights_var.get(), self.rights_var.get())}

    def _snapshot(self, preview=False):
        try:
            return snapshot_form(self._form_values(), preview=preview)
        except (OSError, ValueError) as exc:
            messagebox.showerror('설정 확인', str(exc), parent=self.root)
            self.status_var.set(str(exc))
            return None

    def choose_batch(self):
        path = filedialog.askopenfilename(parent=self.root, title='검색어 파일 선택',
                filetypes=[('CSV / Excel', '*.csv *.xlsx'), ('모든 파일', '*.*')])
        if path:
            self.batch_file_var.set(path)
            self.input_mode_var.set('file')
            try:
                keywords = _load_keywords(path)
                self.log(f'파일의 검색어 {len(keywords)}개: ' + ', '.join(keywords[:5]))
            except (OSError, ValueError) as exc:
                messagebox.showerror('검색어 파일 확인', str(exc), parent=self.root)

    def choose_output(self):
        folder = filedialog.askdirectory(parent=self.root, title='이미지 저장 폴더 선택')
        if folder:
            self.output_var.set(folder)

    def choose_resume(self):
        folder = filedialog.askdirectory(parent=self.root, title='run.json이 있는 실행 폴더 선택')
        if folder:
            self.resume_var.set(folder)

    def start(self):
        if self.busy or self.closing:
            return
        snapshot = self._snapshot()
        if snapshot:
            self.start_task(lambda stop, emit: _run_collection(snapshot.keywords, snapshot.options,
                output_root=snapshot.output_root, logger=emit, stop_event=stop))

    def preview(self):
        if self.busy or self.closing:
            return
        snapshot = self._snapshot(preview=True)
        if snapshot:
            self.preview_snapshot = None
            self.start_task(lambda stop, emit: search_preview(snapshot, stop, emit))

    def download_selected(self, indices):
        if self.busy or self.closing:
            return
        preview = self.preview_snapshot
        selected = preview.selected(indices) if preview else ()
        if not selected:
            self.status_var.set('먼저 미리보기 후보에 체크하세요.')
            return
        snapshot = preview.form
        options = replace(snapshot.options, limit=min(snapshot.options.limit, len(selected)))
        self.start_task(lambda stop, emit: _run_collection(snapshot.keywords, options,
            output_root=snapshot.output_root, logger=emit, stop_event=stop,
            selected_candidates=selected,
            provider_factory=lambda engine, resolved, browser, stop_event, logger: StaticProvider(selected)))

    def resume(self, retry_failed=False):
        if self.busy or self.closing:
            return
        path = self.resume_var.get().strip()
        if not path:
            self.status_var.set('이어받을 실행 폴더를 선택하세요.')
            return
        try:
            state = _load_run(path)
            options = CollectionOptions(**state['options'])
            for engine in options.engines:
                options.resolve(engine)
            keywords = tuple(state['keywords'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror('실행 기록 확인', str(exc), parent=self.root)
            return
        self.start_task(lambda stop, emit: _run_collection(keywords, options, output_root=Path(path).parent,
            logger=emit, stop_event=stop, resume=path, retry_failed=retry_failed))

    def start_task(self, operation):
        if self.busy or self.closing:
            return False
        self.busy = True
        self.stop_event = threading.Event()
        stop_event, event_queue = self.stop_event, self.events
        self._set_busy(True)
        self.progress['value'] = 0
        self.status_var.set('작업 중…')
        def work():
            try:
                result = operation(stop_event, event_queue.put)
                event_queue.put({'type': 'done', 'result': result})
            except Cancelled as exc:
                event_queue.put({'type': 'cancelled', 'message': str(exc)})
            except NeedsAttention as exc:
                event_queue.put({'type': 'attention', 'message': str(exc)})
            except Exception as exc:
                event_queue.put({'type': 'error', 'message': str(exc)})
            finally:
                event_queue.put({'type': 'finished'})
        self.worker = threading.Thread(target=work, name='image-collector-worker', daemon=True)
        self.worker.start()
        return True

    def _set_busy(self, busy):
        for widget, state in self.form_widgets:
            widget.configure(state='disabled' if busy else state)
        for button in (self.start_button, self.preview_button, self.resume_button, self.retry_button,
                       self.resume_picker, self.resume_entry, self.results_button):
            button.configure(state='disabled' if busy else 'normal')
        self.stop_button.configure(state='normal' if busy else 'disabled')
        self.gallery.download_button.configure(state='disabled' if busy or not self.preview_snapshot else 'normal')
        self._update_preview_availability()

    def stop(self):
        if self.busy:
            self.stop_event.set()
            self.status_var.set('중단 중… 진행 중인 요청이 종료되면 정리합니다.')
            self.stop_button.configure(state='disabled')

    def log(self, message):
        self.log_text.configure(state='normal')
        self.log_text.insert('end', str(message) + '\n')
        self.log_text.see('end')
        self.log_text.configure(state='disabled')

    def handle_event(self, event):
        if self.destroyed or self.closing:
            return
        kind = event.get('type')
        if kind == 'log':
            self.log(event.get('message', ''))
        elif kind == 'progress':
            saved, limit = event.get('saved', 0), event.get('limit', 0)
            self.progress['value'] = min(100, 100 * saved / limit) if limit else 0
            self.status_var.set(f"{event.get('keyword', '')} · {event.get('engine', '')} · 저장 {saved}/{limit}")
        elif kind == 'job':
            result = event.get('result', {})
            self.log(f"{result.get('keyword', '')} / {result.get('engine', '')}: {result.get('status', '')} · {result.get('saved_count', 0)}개" +
                     (f" · {result.get('error')}" if result.get('error') else ''))
        elif kind == 'run':
            self.last_run_dir = Path(event['path'])
            self.resume_var.set(str(self.last_run_dir))
        elif kind == 'preview':
            self.preview_snapshot = event['preview']
            self.gallery.set_preview(self.preview_snapshot.candidates)
            self.gallery.download_button.configure(state='disabled')
        elif kind == 'thumbnail':
            self.gallery.set_candidate_thumbnail(event['index'], event.get('png_bytes'), event.get('error', ''))
        elif kind == 'done':
            result = event.get('result')
            if hasattr(result, 'run_dir'):
                self.last_run_dir = result.run_dir
                self.resume_var.set(str(result.run_dir))
                self.open_results(result.run_dir)
                statuses = {'completed': '수집 완료', 'success': '수집 완료', 'partial': '일부 저장 완료',
                            'empty': '검색 결과 없음', 'cancelled': '수집 중단',
                            'needs_attention': '사용자 확인 필요', 'failed': '수집 실패'}
                self.status_var.set(f"{statuses.get(result.status, result.status)} · 총 {result.saved_count}개 · {result.run_dir}")
                if result.status == 'needs_attention':
                    self.status_var.set('검색엔진 확인 필요 · 동의/차단 화면을 직접 확인하세요. 새 검색 시 브라우저 표시를 켜세요.')
            elif isinstance(result, PreviewSnapshot):
                self.status_var.set(f'검색 미리보기 완료 · 후보 {len(result.candidates)}개. 체크 후 다운로드하세요.')
        elif kind in ('error', 'cancelled'):
            self.log(event.get('message', ''))
            self.status_var.set(('중단됨: ' if kind == 'cancelled' else '작업 실패: ') + event.get('message', ''))
        elif kind == 'attention':
            self.log(event.get('message', ''))
            self.status_var.set('검색엔진 확인 필요 · 브라우저 표시를 켜서 동의/차단 화면을 확인한 뒤 다시 검색하세요.')
        elif kind == 'finished':
            self.busy = False
            self._set_busy(False)

    def open_results(self, path=None):
        path = path or self.resume_var.get().strip() or self.last_run_dir
        if not path:
            self.status_var.set('결과가 있는 실행 폴더를 선택하세요.')
            return
        try:
            state = _load_run(path)
            self.gallery.set_items(items_from_manifest(path, state), run_dir=path)
            self.preview_snapshot = None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.log('결과 열기 실패: ' + str(exc))
            self.status_var.set('결과 열기 실패: ' + str(exc))

    def _pump(self):
        self.after_id = None
        if self.destroyed:
            return
        if self.closing:
            if not self.worker or not self.worker.is_alive():
                self.destroyed = True
                self.root.destroy()
                return
        else:
            # Bound each pump to keep Tk responsive when providers emit many logs.
            for _ in range(150):
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                self.handle_event(event)
        self.after_id = self.root.after(80, self._pump)

    def close(self):
        if self.destroyed or self.closing:
            return
        self.closing = True
        self.stop_event.set()
        self.status_var.set('종료 중… 작업과 브라우저를 정리합니다.')
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        if not self.worker or not self.worker.is_alive():
            self.destroyed = True
            self.root.destroy()
        else:
            self.after_id = self.root.after(80, self._pump)


def launch_gui():
    root = tk.Tk()
    CollectorGUI(root)
    root.mainloop()
