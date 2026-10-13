# GUI/gallery implementation report

Historical module handoff snapshot. Subsequent integration fixes and final results supersede the interim behavior/test counts below; see [final verification](verification.md).

Owned files: `image_collector/gui.py`, `image_collector/gallery.py`, `tests/test_gui.py`, this report. No commits or subagents.

Implemented Korean `CollectorGUI(root)` and `launch_gui()`, engine/backend/profile/mode selectors, keyword or fresh CSV/XLSX file input, output directory, size constraints, visible-browser choice, Google filters, start/stop, run resume/retry-failed, queue-driven logs/progress/results, deferred close after worker cleanup. Every worker receives plain immutable snapshots and only writes events into a queue; all Tk reads and updates remain on the main thread.

Gallery reads authoritative saved job records from `load_run`; rejects folder/name escapes, lists filename/dimensions/kind, decodes only the currently selected saved image, shows missing files, opens HTTP(S) source/license links, opens local files/folders safely, and exports selected copies with exclusive filenames without overwriting unrelated files.

Search preview supports one keyword and one browser engine, disabled for batch/both/API with an explanation. Keeps at most 20 original Candidate objects and their snapshot. Thumbnail requests use the real Downloader with min=1 and a 90-second thumbnail deadline; worker scales images to <=180x130 before posting them. Selected download uses StaticProvider with exactly those selected objects and the captured keyword/options, limiting the requested number to the selected number or the original limit. Run results feed the gallery directly; both actual thumbnails and actual saved-image previews are exercised in tests.

TDD evidence:
- Initial RED: 14 tests failed because GUI/gallery implementations did not exist. TemporaryDirectory fixtures were moved into workspace after identifying sandbox TEMP ACL errors; then RED showed feature-missing failures only.
- Next RED: preview logger event normalization, unsupported-preview disablement, and success result localization failed. Implemented and GREEN: 17 tests.
- Next RED: real selected download was classified partial because limit=50 despite 2 selected candidates; verification block lacked Korean actionable status. Implemented and GREEN: 19 tests.
- Final GUI command: `.venv/Scripts/python.exe -m unittest tests.test_gui -q`: 19 tests PASS. Hidden real Tk windows, event pumping, actual Pillow/ImageTk image display, worker snapshot/selection preservation, cancellation/close, safe export and data-image preview tests all pass with no Tcl warnings.
- Hidden layout smoke requested 1071x715 pixels on a 1920x1080 desktop; configured window 1120x860 fits.

Full suite attempted under normal sandbox using workspace TEMP/TMP: 105 tests in 44.171s, 13 failures and 20 errors. All GUI, models, runner, storage, legacy tests passed. Root CLI was still absent at suite start. Downloader HTTP and DOM Selenium fixture failures show PermissionError WinError10013 on 127.0.0.1, so root integration should run full suite outside restricted socket sandbox once parallel work is final.

Full-suite failing names recorded (not hidden):
- CLI: test_batch_encoding_and_both_cli, test_failure_and_cancel_return_nonzero, test_google_default_options_reach_runner, test_invalid_original_naver_stops_before_runner, test_resume_loads_saved_options_without_default_overrides.
- Downloader failures: test_5xx_exhaustion_is_bounded, test_connection_timeouts_retry_and_response_is_closed_after_header_rejection, test_content_length_over_limit_is_rejected_before_body_read, test_deadline_bounds_retry_after, test_deadline_during_stream_is_honored_without_fallback, test_original_only_never_uses_thumbnail_on_invalid_or_failed_original, test_pixel_limit_checked_before_expensive_decode, test_stream_limit_enforced_without_content_length.
- Downloader errors: test_429_retry_after_zero_then_success, test_5xx_retries_three_attempts_and_can_succeed, test_actual_size_and_orientation_are_checked_without_upscaling (3 profile subcases), test_cancel_during_retry_after_never_falls_back, test_cancel_during_stream_is_cancelled_without_fallback, test_exif_orientation_applied_before_dimensions, test_generic_or_missing_content_type_requires_valid_decode, test_hash_matches_persisted_rgba_dimensions_contract, test_original_is_converted_to_rgba_png_and_records_actual_url, test_pixel_duplicate_across_urls_does_not_mutate_seen_hashes, test_preferred_missing_original_is_explicit_fallback, test_preferred_records_http_failure_and_uses_thumbnail, test_redirect_body_is_not_loaded_or_decoded, test_redirect_records_actual_url_and_does_not_forward_sensitive_session_state, test_same_pixels_different_dimensions_are_not_duplicate, test_streamed_read_timeout_is_retried_three_times, test_thumbnail_mode_skips_original_and_uses_engine_referer.
- Providers: DOMProviderTests.setUpClass local Selenium fixture socket error.

Limits: API preview is intentionally disabled; normal API collection remains available. Live Google search was not re-probed by this agent; browser/provider agent reports a traffic block, correctly surfaced as user attention rather than empty/success. OS web/file opens were not invoked during tests to avoid opening external helpers; URL safety decisions and export filesystem effects are tested directly. Final full-suite verification remains with root after all integrations are present.
