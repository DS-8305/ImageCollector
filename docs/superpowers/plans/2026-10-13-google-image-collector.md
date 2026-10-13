# Google Image Collector Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for integration and superpowers:dispatching-parallel-agents for independent provider/downloader modules. Steps use checkbox syntax for tracking.

**Goal:** Ship the desktop/CLI collector for Naver and Google, production-size images, reliable storage, batch jobs, combined engines, resume/retry, result gallery and an optional external search API.
**Architecture:** Providers emit Candidate objects; Downloader validates and returns DownloadedImage; Runner owns sessions, work budgets and state; RunStore preserves immutable run outputs. GUI uses a queue and snapshots Tk variables before workers start.
**Tech Stack:** Python 3.10+, unittest, Selenium, requests, Pillow, openpyxl, Tkinter.
**Spec:** docs/superpowers/specs/2026-10-13-google-image-collector-design.md

## Global Constraints

- Preserve legacy no-argument GUI and --keyword/--batch-file/--limit/--min-thumbnail-size commands.
- No engine means naver, thumbnail/150px. Google defaults original-only/blog (long edge 1200px).
- Profiles: blog long edge >=1200, both edges >=150; landscape >=1920x1080; portrait >=1080x1920.
- Preserve previous outputs, separate run/keyword/engine, safe folders with hash, atomic JSON state.
- Browser owner is one worker; reuse sequentially; stop and close all resources.
- All statuses and fallback reasons visible; zero images is never success.
- Both engines target limit per engine. Resume is explicit; never mix incompatible options.
- Optional API uses SERPAPI_API_KEY only if user explicitly selects api; never auto-switch or buy credits.
- Product UI in Korean. No automatic upscale/crop.
- Final-stage scope includes integrated engines, resume/retry and gallery. Perceptual duplicate detection and watermark recognition remain the spec's uncommitted research directions, not silently claimed implemented.

## Review Focus

- Crash between image rename and JSON checkpoint: recover orphan validated files without losing prior state.
- Changed CSV or XLSX selection: execute freshly validated keyword data.
- Host timeouts, blocked Google, cancelled GUI: stop work without empty/success misclassification or leaks.
- Resume path and incompatible profile/options: reject before modifying files.
- Gallery URLs and previews: use the correct row, lazy thumbnail loads, graceful missing image handling.

## Task 1: Contracts, profiles, batch input
Files: image_collector/models.py, batch_input.py, tests/test_models.py.
Produces: Candidate(thumbnail_url, source_url="", title="", source="", original_url="", engine="", rank=0, license_url=""); CollectionOptions(engine="naver", limit=50, download_mode=None, profile=None, min_width=None, min_height=None, min_long_edge=None, headless=None, max_candidates=None, max_scrolls=30, keyword_timeout=300, backend="browser", period="", usage_rights=""); resolve(engine) -> ResolvedOptions; DownloadedImage(png_bytes,width,height,content_hash,downloaded_url,download_kind,fallback_reason=""); CollectionError, NeedsAttention, Cancelled, RejectedImage, DuplicateImage; JobResult/RunResult.
- [x] Write test_profile_defaults_and_overrides, test_rejects_invalid_options and input compatibility cases.
- [x] Run unittest and verify expected failures.
- [x] Implement profiles, validation, metadata defaults and existing CSV/XLSX loading.
- [x] Run unit tests and baseline legacy tests.

## Task 2: Download and quality module
Files: image_collector/downloader.py, tests/test_downloader.py.
Consumes: Candidate, ResolvedOptions, DownloadedImage.
Produces: Downloader(options, stop_event=None, session=None); download(candidate, seen_hashes=None) -> DownloadedImage; close().
- [x] Write image fixture tests: real PNG/JPEG/WebP/data thumbnail, HTML, sizes, original-only and fallback, identical pixels, stream limits, retry/cancel.
- [x] Run RED, implement chunked requests, per-attempt timeouts, Pillow verification/EXIF orientation/PNG, hash and resource ownership.
- [x] Run GREEN and inspect failed versus rejected outcomes.

## Task 3: Search providers and browser
Files: image_collector/browser.py, providers/base.py, naver.py, google.py, api.py, __init__.py, tests/test_providers.py.
Consumes: Candidate, ResolvedOptions, errors.
Produces: BrowserSession(headless); create_provider(engine, options, browser, stop_event=None, logger=None); provider.search(keyword) -> iterator[Candidate].
- [x] Observe actual Google result DOM using a disposable Chrome session.
- [x] Test extraction and state recognition from observed/hand checked DOM fixtures, changed previews, URL encoding, stop/deadline.
- [x] Implement Naver and Google browser providers, shared explicit waits/scrolling, blocked/consent/empty detection.
- [x] Implement optional SerpApi provider and supported period/usage-rights filters; explicit key required, bounded pagination.
- [x] Run provider tests and small live search; record actual support/limitations.

## Task 4: Reliable store, runner, combined engines and resume
Files: image_collector/storage.py, runner.py, tests/test_runner.py, test_storage.py.
Consumes: providers/downloader contracts.
Produces: run_collection(keywords, options, output_root="downloaded_images", logger=None, stop_event=None, resume=None, retry_failed=False, provider_factory=None, downloader_factory=None, selected_candidates=None) -> RunResult(run_dir, jobs, status); load_run(path) -> dict.
- [x] Write regression tests for preservation, folder collisions, zero/partial, blocked engine, both engines, limits/cancel, resume and mismatch, orphan recovery.
- [x] Run RED; implement atomic state/PNG handling, metadata exports, validated resume, resource lifetime and structured events.
- [x] Run GREEN with real fake providers and real downloaded image objects.

## Task 5: CLI, GUI and compatibility
Files: image_collector/cli.py, gui.py, gallery.py, __main__.py, naver_image_collector.py, tests/test_cli.py, test_gui.py.
Consumes: run_collection, load_keywords, models.
- [x] Test CLI exit codes/config, GUI option snapshots/input changes/result mapping using fake external calls or live Tk as appropriate.
- [x] Run RED; implement engine/both selection, profile/options, stop, queue events, resume and retry, API key environment notice, result gallery/open source/selection copy.
- [x] Preserve old import surface where practical; update outdated legacy assertions only for deliberate behavior changes.
- [x] Run GUI smoke: instantiate, events, image gallery, worker completion and close; CLI help/validation.

## Task 6: Verification and delivery
Files: README.md, requirements.txt, .github/workflows/tests.yml, run_collector.ps1, docs/verification.md.
- [x] Run whole suite and compile checks.
- [x] Run small live Naver/Google keyword and Google batch if external state permits; never imply success from mocks.
- [x] Independent review of correctness/security/resume/UI, fix meaningful findings with regression tests.
- [x] Document install/start/config/output and actual verification.
- [ ] Commit final implementation on codex branch and prepare reviewable GitHub draft PR when available.

Verification: 129 tests PASS, compileall PASS, launcher reports 2.0.0. Naver live 3/3 saved; Google live verification screen prevented original download and batch verification. Six independent review findings have regression coverage and fixes. Delivery pending branch push and draft PR.
