"""Backward-compatible entry point for Image Collector 2."""
from image_collector.compat import (
    BatchResult, ImageCandidate, ImageRecord, NaverImageCollector, NaverImageCollectorGUI,
    build_parser, clear_generated_images, collect_single_keyword, ensure_keyword_folder,
    load_keywords, run_batch_collection, safe_folder_name, write_metadata,
)
from image_collector.cli import main
from image_collector.gui import launch_gui

if __name__ == "__main__":
    raise SystemExit(main())
