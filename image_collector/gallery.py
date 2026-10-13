"""Lazy desktop image gallery and safe, non-destructive selection export."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlsplit
import webbrowser


@dataclass(frozen=True)
class GalleryItem:
    path: Path
    width: int = 0
    height: int = 0
    kind: str = ''
    source_url: str = ''
    license_url: str = ''
    title: str = ''


def items_from_manifest(run_dir, manifest):
    """Read authoritative saved rows; never follow paths outside the run."""
    root = Path(run_dir).resolve()
    items = []
    for job in manifest.get('jobs', {}).values():
        folder = (root / job.get('folder', '')).resolve()
        if not folder.is_relative_to(root):
            continue
        for row in job.get('records', []):
            name = row.get('file_name', '')
            if row.get('status') != 'saved' or not name or Path(name).name != name:
                continue
            path = (folder / name).resolve()
            if not path.is_relative_to(folder):
                continue
            items.append(GalleryItem(path, int(row.get('width') or 0), int(row.get('height') or 0),
                                     row.get('download_kind', ''), row.get('source_url', ''),
                                     row.get('license_url', ''), row.get('title', '')))
    return items


def open_web_url(url):
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme.lower() in ('http', 'https') and bool(parsed.hostname) and not parsed.username and not parsed.password
    except (TypeError, ValueError):
        valid = False
    if not valid:
        return False
    webbrowser.open(url)
    return True


def open_local_path(path):
    target = Path(path).resolve()
    if not target.exists():
        raise FileNotFoundError('파일 또는 폴더가 없습니다: ' + str(target))
    if os.name == 'nt':
        os.startfile(str(target))
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(target)])


def export_selection(paths, destination):
    """Reserve output filenames exclusively, preserving existing destination files."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in map(Path, paths):
        if not source.is_file():
            continue
        suffix = 0
        while True:
            name = source.name if not suffix else f'{source.stem}_{suffix + 1}{source.suffix}'
            target = destination / name
            try:
                output = target.open('xb')
                break
            except FileExistsError:
                suffix += 1
        try:
            with source.open('rb') as input_file, output:
                shutil.copyfileobj(input_file, output)
        except BaseException:
            output.close()
            target.unlink(missing_ok=True)
            raise
        copied.append(target)
    return copied


class Gallery(ttk.Frame):
    """Only the selected saved image is decoded; candidate thumbnails are bounded."""
    def __init__(self, master, on_download=None):
        super().__init__(master)
        self.items = []
        self.candidates = ()
        self.checked = set()
        self.photo = None
        self.preview_photos = {}
        self.candidate_checks = []
        self.candidate_labels = []
        self.current = None
        self.run_dir = None
        self.on_download = on_download
        self.detail_var = tk.StringVar(value='결과를 선택하면 이미지와 출처를 확인할 수 있습니다.')
        toolbar = ttk.Frame(self)
        toolbar.pack(fill='x', pady=(0, 5))
        ttk.Button(toolbar, text='전체 선택', command=self.select_all).pack(side='left')
        ttk.Button(toolbar, text='선택 해제', command=self.clear_selection).pack(side='left', padx=4)
        self.export_button = ttk.Button(toolbar, text='선택 이미지 내보내기', command=self.export)
        self.export_button.pack(side='left')
        self.download_button = ttk.Button(toolbar, text='선택한 후보 다운로드', command=self.download_selected, state='disabled')
        self.download_button.pack(side='left', padx=4)
        self.body = ttk.Frame(self)
        self.body.pack(fill='both', expand=True)
        self.left = ttk.Frame(self.body)
        self.left.pack(side='left', fill='both', expand=True)
        self.tree = ttk.Treeview(self.left, columns=('check', 'filename', 'size', 'kind'), show='headings', height=9)
        for column, title, width in [('check', '선택', 45), ('filename', '파일 이름', 260),
                                     ('size', '가로 × 세로', 125), ('kind', '저장 종류', 100)]:
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, stretch=column == 'filename')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree_scroll = ttk.Scrollbar(self.left, orient='vertical', command=self.tree.yview)
        self.tree_scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=self.tree_scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self._selection)
        self.tree.bind('<Button-1>', self._toggle_click)
        self.cards_canvas = tk.Canvas(self.left, height=300, highlightthickness=0)
        self.cards_scroll = ttk.Scrollbar(self.left, orient='vertical', command=self.cards_canvas.yview)
        self.cards_canvas.configure(yscrollcommand=self.cards_scroll.set)
        self.cards = ttk.Frame(self.cards_canvas)
        self.cards_window = self.cards_canvas.create_window((0, 0), window=self.cards, anchor='nw')
        self.cards.bind('<Configure>', lambda event: self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox('all')))
        self.cards_canvas.bind('<Configure>', lambda event: self.cards_canvas.itemconfigure(self.cards_window, width=event.width))
        right = ttk.Frame(self.body, width=300)
        right.pack(side='right', fill='y', padx=(12, 0))
        self.preview_label = ttk.Label(right, text='이미지 미리보기', anchor='center')
        self.preview_label.pack(fill='both', expand=True)
        ttk.Label(right, textvariable=self.detail_var, wraplength=300).pack(fill='x', pady=5)
        buttons = ttk.Frame(right)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='출처', command=lambda: self.open_link('source_url')).pack(side='left')
        ttk.Button(buttons, text='라이선스', command=lambda: self.open_link('license_url')).pack(side='left', padx=3)
        ttk.Button(buttons, text='파일', command=self.open_file).pack(side='left')
        ttk.Button(buttons, text='폴더', command=self.open_folder).pack(side='left', padx=3)

    def set_items(self, items, run_dir=None):
        self.items = list(items)
        self.candidates = ()
        self.checked.clear()
        self.current = None
        self.run_dir = Path(run_dir) if run_dir else None
        self._clear_cards()
        self.cards_canvas.pack_forget()
        self.cards_scroll.pack_forget()
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree_scroll.pack(side='right', fill='y')
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.items):
            self.tree.insert('', 'end', iid=str(index), values=('☐', item.path.name,
                f'{item.width} × {item.height}' if item.width else '정보 없음',
                {'original': '원본', 'thumbnail': '썸네일'}.get(item.kind, item.kind)))
        self.download_button.configure(state='disabled')
        self.export_button.configure(state='normal')
        self.photo = None
        self.preview_label.configure(image='', text='이미지 미리보기')
        self.detail_var.set(f'저장 이미지 {len(self.items)}개. 왼쪽 목록에서 선택하세요.')

    def _clear_cards(self):
        for widget in self.cards.winfo_children():
            widget.destroy()
        self.preview_photos.clear()
        self.candidate_checks.clear()
        self.candidate_labels.clear()

    def set_preview(self, candidates):
        self.candidates = tuple(candidates)
        self.checked.clear()
        self.items = []
        self.current = None
        self._clear_cards()
        self.tree.pack_forget()
        self.tree_scroll.pack_forget()
        self.cards_canvas.pack(side='left', fill='both', expand=True)
        self.cards_scroll.pack(side='right', fill='y')
        for index, candidate in enumerate(self.candidates):
            card = ttk.Frame(self.cards, padding=6, relief='ridge')
            card.pack(fill='x', pady=3)
            checked = tk.BooleanVar(value=False)
            self.candidate_checks.append(checked)
            ttk.Checkbutton(card, text='선택', variable=checked).pack(side='left', anchor='n')
            image_label = ttk.Label(card, text='썸네일 준비 중', width=22, anchor='center')
            image_label.pack(side='left', padx=6)
            self.candidate_labels.append(image_label)
            info = ttk.Frame(card)
            info.pack(side='left', fill='both', expand=True)
            ttk.Label(info, text=candidate.title or f'후보 {index + 1}', wraplength=330).pack(anchor='w')
            ttk.Label(info, text=candidate.source or candidate.source_url, wraplength=330).pack(anchor='w')
            quality = '원본 URL 있음 · 실제 크기는 저장 시 검증' if candidate.original_url else '원본 URL 없음 · 썸네일 후보'
            ttk.Label(info, text=quality, wraplength=330).pack(anchor='w')
            ttk.Button(info, text='출처 확인', command=lambda c=candidate: open_web_url(c.source_url)).pack(anchor='w')
        self.download_button.configure(state='normal' if self.candidates else 'disabled')
        self.export_button.configure(state='disabled')
        self.photo = None
        self.preview_label.configure(image='', text='후보 썸네일은 왼쪽에 표시됩니다.')
        self.detail_var.set(f'후보 {len(self.candidates)}개. 체크한 후보만 저장합니다. 크기 기준을 통과하지 못하면 저장되지 않습니다.')

    def set_candidate_thumbnail(self, index, png_bytes=None, error=''):
        if index >= len(self.candidate_labels):
            return
        label = self.candidate_labels[index]
        if png_bytes:
            from PIL import Image, ImageTk
            with Image.open(BytesIO(png_bytes)) as image:
                image.thumbnail((180, 130))
                photo = ImageTk.PhotoImage(image.copy(), master=self)
            self.preview_photos[index] = photo
            label.configure(image=photo, text='', width=0)
        else:
            label.configure(text='썸네일을 표시할 수 없습니다')

    def selected_indices(self):
        return [index for index, value in enumerate(self.candidate_checks) if value.get()]

    def select_all(self):
        if self.candidates:
            for value in self.candidate_checks:
                value.set(True)
        else:
            self.checked = set(range(len(self.items)))
            self._refresh_checks()

    def clear_selection(self):
        self.checked.clear()
        for value in self.candidate_checks:
            value.set(False)
        self._refresh_checks()

    def _refresh_checks(self):
        for index in range(len(self.items)):
            self.tree.set(str(index), 'check', '☑' if index in self.checked else '☐')

    def _toggle_click(self, event):
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x) == '#1':
            index = int(row)
            self.checked.symmetric_difference_update({index})
            self._refresh_checks()

    def _selection(self, event=None):
        selection = self.tree.selection()
        if selection:
            self.show_item(int(selection[0]))

    def show_item(self, index):
        self.current = self.items[index]
        item = self.current
        self.photo = None
        if not item.path.is_file():
            self.preview_label.configure(image='', text='파일 없음')
            self.detail_var.set('파일이 없거나 이동되었습니다: ' + str(item.path))
            return
        try:
            from PIL import Image, ImageTk
            with Image.open(item.path) as image:
                image.thumbnail((300, 210))
                self.photo = ImageTk.PhotoImage(image.copy(), master=self)
            self.preview_label.configure(image=self.photo, text='')
            self.detail_var.set(f'{item.path.name}\n{item.width} × {item.height} · {item.kind}\n{item.title}')
        except Exception as exc:
            self.preview_label.configure(image='', text='미리보기 실패')
            self.detail_var.set(f'이미지를 열 수 없습니다: {exc}')

    def open_link(self, attribute):
        if not self.current or not open_web_url(getattr(self.current, attribute)):
            self.detail_var.set('열 수 있는 웹 주소가 없습니다. 라이선스는 출처에서 직접 확인하세요.')

    def open_file(self):
        self._open(self.current.path if self.current else None)

    def open_folder(self):
        self._open(self.current.path.parent if self.current else self.run_dir)

    def _open(self, path):
        if path is None:
            self.detail_var.set('먼저 결과를 선택하세요.')
            return
        try:
            open_local_path(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror('열기 실패', str(exc), parent=self.winfo_toplevel())

    def export(self):
        if not self.checked:
            self.detail_var.set('내보낼 이미지에 체크하세요.')
            return
        folder = filedialog.askdirectory(title='선택 이미지를 복사할 폴더', parent=self.winfo_toplevel())
        if folder:
            try:
                paths = export_selection([self.items[index].path for index in sorted(self.checked)], folder)
                self.detail_var.set(f'{len(paths)}개 이미지를 복사했습니다. 기존 파일은 보존됩니다.')
            except OSError as exc:
                messagebox.showerror('내보내기 실패', str(exc), parent=self.winfo_toplevel())

    def download_selected(self):
        if self.on_download:
            self.on_download(self.selected_indices())
