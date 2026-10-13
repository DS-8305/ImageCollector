# Search provider implementation report

Historical module handoff snapshot. Subsequent integration fixes and final results supersede the interim behavior/test counts below; see [final verification](verification.md).

2026-10-13. Scope: `image_collector/browser.py`, `image_collector/providers/*`, `tests/test_providers.py`, `tests/fixtures/provider*.html`, and `scripts/probe_search.py`. No commits made.

## Implemented

- Lazy, reusable `BrowserSession(headless=False)` with explicit close; Selenium Manager first and webdriver-manager fallback. Cache is project-local `.browser-cache/`.
- `create_provider(engine, options, browser, stop_event=None, logger=None)` for Naver, Google browser, and optional Google SerpApi. Browser adapters do not close the shared run browser; API adapter closes its own HTTP session.
- Naver preserves `sort=date` request and thumbnail mode. Scoped grid images are extracted, with a fallback to the initial `imageSearchTabData.content.items` search-result payload observed in actual Naver HTML. Original URLs present in that payload are deliberately not exposed as an unvalidated Naver capability.
- Google scopes extraction to result cards, supports HTTP and supported inline image thumbnails, and skips detail clicks in thumbnail mode. Original modes inspect imgres/card metadata or select the card and explicitly wait for a detail-image URL different from the previous detail. Missing detail originals remain empty rather than copying an old candidate's image. Source-page and image-file URLs remain separate.
- Google requests date filters through `tbs=qdr:d/w/m/y`, rights through `tbs=sur:cl/ol`. The API uses documented `period_unit` and `licenses` parameters. These filters indicate search filtering, not a guarantee of reuse permission.
- Initial readiness, scrolling, candidate counts, detail waits, keyword deadlines, cancellation, and stale rounds are bounded. CAPTCHA, unusual traffic, and consent raise `NeedsAttention`; explicit empty results finish normally; unrecognized DOM raises `CollectionError`. A result title containing “no results found” is not classified as empty when actual result cards exist.
- SerpApi uses `SERPAPI_API_KEY`, fixed trusted endpoint, documented `images_results` fields, bounded `ijn` pagination (at most 100 pages and user bound), duplicate-page stop, and at most three transport/5xx attempts. Authorization/quota/HTTP 429 stops with `NeedsAttention`. Exception messages do not print request URLs/API keys. Cancellation is checked after responses as well as before calls.

## Verification evidence

- First TDD RED: 4 missing implementation failures. GREEN: 4 tests.
- Next RED: API search missing, plus local Chrome fixture tests missing browser search. GREEN: 13 tests.
- Documentation correction RED: browser rights parameter and API dedicated filter assertions failed. GREEN after correction and observed Naver fallback: 15 tests.
- Edge-case RED: API response cancellation did not raise; a “no results found” card title incorrectly returned no candidates. GREEN after fixes: 18 tests.
- Final provider set: 21 tests. These include real local Chrome DOM execution, delayed detail transitions, stale detail rejection, logo exclusion, inline thumbnail mode, initial-payload extraction, captured live CAPTCHA detection, API retries, duplicate/bounded pagination, cancellation, quota, and key-safe errors.
- Full project command: `.venv/Scripts/python.exe -m unittest discover -s tests -v` passed **117 tests in 17.605 seconds**, no failures or skips, on the workspace state available during this run. Chrome tests required an authorized sandbox escalation because ChromeDriver uses a localhost service; fixture tests block external HTTP/HTTPS requests with Chrome DevTools.
- After capture identifier redaction, reran the two captured live-fixture tests; both passed.

## Actual external observations and limits

Initial restricted-network Google probe could not download/start a driver. The authorized escalated disposable Chrome probe then ran successfully as a probe and returned Google's `/sorry/index` verification page, with the actual “unusual traffic” message and zero result-card selectors. `provider_google_live.html` captures that observed block with network/challenge identifiers redacted. The provider recognizes this captured page as `NeedsAttention`. No CAPTCHA bypass or repeated Google search retries were attempted.

Consequently, **live Google original extraction and filtered result correctness were not demonstrated**. Result-card/detail fixtures exercise the supported extraction behavior in real Chrome, but current Google result markup still needs validation on a network where Google permits the search. Unrecognized layouts fail explicitly. This is a material release limitation, not a live success claim.

One authorized Naver probe loaded the image result page. Observed selectors: `div.image_tile` = 1; `img._image` = 0; image grid still showed its loading spinner. The actual HTML included populated `window.imageSearchTabData.content.items` with thumbnail/source-page/title fields. The saved `provider_naver_live.html` supports a regression test proving extraction of the observed Colourbox first source page and Naver thumbnail while the grid is loading. This observation proves initial candidate availability; it does not prove complete infinite scrolling or image-download success. Root integration should exercise those separately.

SerpApi was not called live because no account/key purchase or key retrieval was authorized. Schema/transport/pagination checks use controlled external-boundary doubles.

`scripts/probe_search.py` is a disposable probe and never downloads source images. Do not interpret its process exit code alone as collection success: emitted `status=needs_attention` and page observations identify a Google block.

Primary references inspected: [Selenium waits](https://www.selenium.dev/documentation/webdriver/waits/) and [SerpApi Google Images API](https://serpapi.com/google-images-api), including `ijn`, `period_unit`, `licenses`, `images_results`, and `license_details_url`.

Integration note: add `.browser-cache/` to `.gitignore` in the root's owned integration scope; ChromeDriver is a disposable local dependency, not a source artifact.
