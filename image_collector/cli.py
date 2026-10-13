"""Command line entry point. Defaults are resolved per engine and resume records."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
import sys
import threading

from . import __version__
from .batch_input import load_keywords
from .models import CollectionOptions, PROFILES
from .runner import run_collection, load_run


def build_parser():
    parser = argparse.ArgumentParser(description="네이버·구글 이미지 수집")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--keyword",help="단일 검색어")
    input_group.add_argument("--batch-file",help="keyword 열이 있는 CSV/XLSX")
    parser.add_argument("--engine",choices=("naver","google","both"),help="기본 naver; both는 엔진별 목표 수")
    parser.add_argument("--backend",choices=("browser","api"),help="api는 구글/명시적 SERPAPI_API_KEY 필요")
    parser.add_argument("--limit",type=int,help="엔진별 유효 이미지 목표 수 (기본 50)")
    parser.add_argument("--profile",choices=tuple(PROFILES),help="구글 기본 blog, 네이버 기본 legacy-thumbnail")
    parser.add_argument("--download-mode",choices=("thumbnail","original-only","original-preferred"))
    parser.add_argument("--min-thumbnail-size",type=int,help="기존 옵션: 최소 가로·세로")
    parser.add_argument("--min-width",type=int)
    parser.add_argument("--min-height",type=int)
    parser.add_argument("--min-long-edge",type=int)
    parser.add_argument("--output-dir",help="기본 downloaded_images")
    browser = parser.add_mutually_exclusive_group()
    browser.add_argument("--show-browser",action="store_true",default=None)
    browser.add_argument("--headless",action="store_true",default=None)
    parser.add_argument("--max-candidates",type=int)
    parser.add_argument("--max-scrolls",type=int)
    parser.add_argument("--keyword-timeout",type=float,help="키워드 제한 시간(초), 기본 300")
    parser.add_argument("--period",choices=("day","week","month","year"))
    parser.add_argument("--usage-rights",choices=("creative-commons","commercial"),help="구글의 검색 필터; 사용 허가 판단 아님")
    parser.add_argument("--resume",help="기존 run 폴더 또는 run.json")
    parser.add_argument("--retry-failed",action="store_true",help="이어받기에서 실패·미완료 작업만 재실행")
    parser.add_argument("--gallery",help="기존 run 결과 갤러리 열기")
    parser.add_argument("--gui",action="store_true")
    parser.add_argument("--version",action="version",version=__version__)
    return parser


def options_from_args(args, saved=None):
    values = dict(saved or {})
    for field in ("engine","backend","limit","profile","download_mode","min_width","min_height",
                  "min_long_edge","max_candidates","max_scrolls","keyword_timeout","period","usage_rights"):
        value = getattr(args,field,None)
        if value is not None:
            values[field] = value
    if args.min_thumbnail_size is not None:
        values["min_width"] = args.min_width if args.min_width is not None else args.min_thumbnail_size
        values["min_height"] = args.min_height if args.min_height is not None else args.min_thumbnail_size
    if args.show_browser:
        values["headless"] = False
    elif args.headless:
        values["headless"] = True
    options = CollectionOptions(**values)
    for engine in options.engines:
        options.resolve(engine)
    return options


def print_event(event):
    if event["type"] == "log":
        print(event["message"],flush=True)
    elif event["type"] == "run":
        print("결과 폴더:",event["path"],flush=True)
    elif event["type"] == "progress":
        print(f'{event["engine"]} / {event["keyword"]}: {event["saved"]}/{event["limit"]}',flush=True)
    elif event["type"] == "job":
        job = event["result"]
        print(f'{job["engine"]} / {job["keyword"]}: {job["status"]}, {job["saved_count"]}장'
              + (f' / {job["error"]}' if job["error"] else ""),flush=True)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.gallery:
        from .gallery import Gallery, items_from_manifest
        import tkinter as tk
        try:
            data = load_run(args.gallery)
            root = tk.Tk()
            root.title("이미지 수집 결과")
            root.geometry("1080x700")
            path = Path(args.gallery).resolve()
            if path.name == "run.json":
                path = path.parent
            gallery = Gallery(root)
            gallery.pack(fill="both",expand=True)
            gallery.set_items(items_from_manifest(path,data),run_dir=path)
            root.protocol("WM_DELETE_WINDOW",root.destroy)
            root.mainloop()
            return 0
        except (ValueError,OSError) as exc:
            print(str(exc),file=sys.stderr)
            return 2
    if args.gui or not (args.keyword or args.batch_file or args.resume):
        if args.retry_failed:
            print("--retry-failed에는 --resume이 필요합니다.",file=sys.stderr)
            return 2
        from .gui import launch_gui
        launch_gui()
        return 0
    stop = threading.Event()
    try:
        saved = load_run(args.resume) if args.resume else None
        options = options_from_args(args,saved["options"] if saved else None)
        if args.batch_file:
            keywords = load_keywords(args.batch_file)
        elif args.keyword:
            keywords = [args.keyword]
        elif saved:
            keywords = saved["keywords"]
        else:
            raise ValueError("검색어 또는 입력 파일이 필요합니다.")
        result = run_collection(keywords,options,output_root=args.output_dir or "downloaded_images",
                                logger=print_event,stop_event=stop,resume=args.resume,retry_failed=args.retry_failed)
        print(f"완료 상태: {result.status} / 저장 {result.saved_count}장 / {result.run_dir}")
        if result.status == "cancelled":
            return 130
        return 1 if result.status in ("failed","needs_attention") else 0
    except KeyboardInterrupt:
        stop.set()
        print("사용자가 실행을 중단했습니다.",file=sys.stderr)
        return 130
    except (ValueError,OSError,RuntimeError) as exc:
        print(f"실행 오류: {exc}",file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
