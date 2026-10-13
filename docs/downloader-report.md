# Downloader implementation report

Historical module handoff snapshot. Subsequent integration fixes and final results supersede the interim behavior/test counts below; see [final verification](verification.md).

Implemented only `image_collector/downloader.py`, `tests/test_downloader.py`, and this report. No commits or subagents.

## Behavior

- Original-only, original-preferred (with explicit reason), and thumbnail paths share actual image quality checks. Invalid/missing/data original URLs never become network requests. Duplicate originals raise DuplicateImage rather than silently choosing a thumbnail.
- HTTP(S) URL/redirect validation rejects credentials and unsupported schemes. Originals use a valid source-page Referer; thumbnails use their engine Referer.
- Requests are prepared independently of session cookies/auth/default headers and transmitted through the session's actual HTTP adapter, retaining TLS/proxy settings. Redirects are explicitly followed (maximum five), validating every destination. Adapter transport avoids requests.Session.send's hidden redirect-body consumption and authentication reinjection.
- Streamed decoded transfer size is capped at 20MiB; base64 JPEG/PNG/WebP thumbnails are capped at 2MiB; decoded images are capped at 40 million pixels before load. Wrong declared text Content-Type, HTML, unsupported formats and corrupt images are rejected. Generic/missing Content-Type requires valid image decoding.
- Pillow verify plus load, EXIF orientation, RGBA PNG output, actual options.accepts_size thresholds, and no resizing/cropping. Hash format matches storage/resume: SHA256 of ASCII `widthxheight:` plus normalized RGBA pixels. Seen hashes are never mutated.
- Three attempts maximum for connect/read timeouts, 5xx, and 429. Retry-After accepts seconds or HTTP dates, capped at five seconds; waits are cancellable and require available deadline budget. 403/404 and invalid images are not retried. Responses close in finally; owned sessions close once; injected sessions remain caller-owned.

## RED and GREEN evidence

1. First test run: `python -m unittest tests.test_downloader.DownloadTests.test_original_is_converted_to_rgba_png_and_records_actual_url -v` failed with an explicit missing Downloader-contract assertion. The initial entire 27-test file failed (41 failure/subtest records) before production code existed.
2. Local HTTP tests initially encountered sandbox WinError 10013. Running the same tests with approved localhost socket access exposed the real code results. No external URLs are fetched by these tests.
3. Initial 27-test GREEN: 27 tests / 2.955 seconds / OK. A mismatched test fixture (Google candidate paired with Naver options) was corrected to use a Naver candidate.
4. Redirect regression RED: delayed irrelevant redirect body consumed the deadline through Session.send. Switching to adapter-level transport made the real redirect test pass without reading its body.
5. Persisted-hash compatibility RED: expected `d6a3a932...98cb6f2d`, got `6fe90144...a61439aa`. Aligning the dimensions prefix with existing storage fixed it.
6. Final targeted GREEN: `.venv/Scripts/python.exe -m unittest tests.test_downloader -q` ran **33 tests in 4.578 seconds, OK**. Includes real streamed read-timeout retries, connect-timeout fault injection at the actual adapter boundary, stream cancellation, deadline exhaustion, and real response closure after header rejection. `compileall` passed for both owned Python files before the final hash-only change.

## Full-suite snapshots while other components were in progress

The first full `unittest discover -v` ran 91 tests with 31 failures, zero downloader failures. GUI implementation was missing, and provider search methods were not yet implemented. A subsequent full discovery using a concise unittest runner ran 100 tests with 28 failures / 0 errors, zero downloader failures. Provider failures had disappeared; GUI and runner work was still in progress. Whole-project GREEN is **not claimed**; root integration must rerun discovery after those components finish.

Latest failing GUI tests (19 failure/subtest records):

- `tests.test_gui.FormTests.test_both_default_modes_are_resolved_per_engine`
- `test_original_mode_with_naver_has_actionable_validation` (naver, both)
- `test_preview_preserves_original_candidate_objects_and_form_snapshot`
- `test_preview_requires_single_browser_engine_and_keyword` (both, API backend, file input)
- `test_same_batch_path_is_reloaded_on_every_snapshot`
- `test_size_overrides_and_browser_visibility_captured`
- `test_zero_and_non_integer_inputs_rejected_before_work` (limit zero/noninteger, min_width zero, negative long edge, blank keyword, blank output root)
- `tests.test_gui.TkTests.test_close_signals_stop_and_defers_destroy_until_worker_exits`
- `test_gallery_renders_actual_preview_and_missing_file_message`
- `test_hidden_live_tk_form_builds_and_status_progress_events_display`
- `test_worker_uses_captured_values_and_only_queues_events`

Latest failing runner tests (nine records, under `tests.test_runner.RunnerTests`):

- `test_blocked_google_stops_google_but_naver_continues`
- `test_cancel_before_start_marks_all_jobs_and_no_browser_work`
- `test_candidate_errors_and_events_do_not_lose_valid_outputs`
- `test_duplicate_keywords_process_once_and_limit_enforced`
- `test_incompatible_resume_rejected_without_changing_manifest`
- `test_partial_count_and_both_engines`
- `test_resume_preserves_complete_job_and_retries_partial`
- `test_true_empty_distinct_from_provider_failure`
- `test_zero_downloads_failed_not_success`

Earlier provider failures (subsequently gone): `tests.test_providers.DOMProviderTests.test_block_consent_empty_and_dom_change_remain_distinct` (blocked/consent/changed/empty fixtures), `test_google_cards_exclude_logo_and_keep_data_thumbnail_without_click`, `test_google_stale_detail_is_not_assigned_to_next_card`, `test_google_waits_for_each_detail_change_and_keeps_source_distinct`, `test_naver_scoped_thumbnails_preserve_latest_sort`, `test_pre_cancelled_browser_search_never_navigates`; `tests.test_providers.ProviderTests.test_api_blocked_error_is_attention_and_missing_result_schema_is_failure`, `test_api_keeps_original_source_thumbnail_and_license_distinct`, `test_cancelled_api_does_not_make_a_request`.

## Limits and integration notes

- Stop and deadline checks run before transfer, at each received chunk, before/after decoding and encoding, and during retry waits. Requests timeouts are at most 20 seconds and bounded by remaining deadline. Cancellation cannot interrupt a currently blocked native socket/Pillow operation; a server dripping bytes may extend an inactivity-based socket read until the next chunk boundary. If root requires an absolute hard interrupt during native calls, that needs an additional transport watchdog/process design.
- Normalization chooses the first frame for animated supported inputs. This brief does not specify animation preservation.
- Tests use real local HTTP and generated input, plus narrow adapter fault injection for connect timeout (not reliably reproducible on localhost) and a shorter read timeout to keep the real stalled-server regression fast.
- The HTTP session injection contract is requests.Session-compatible (`merge_environment_settings`, `get_adapter`, `close`); a minimal fake exposing only `get` or `send` is insufficient. Root can inject a real session/adapter for network-independent orchestration tests.
