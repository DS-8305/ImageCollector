# Persistent browser and verification handling

> Execution: implement inline with superpowers:executing-plans and test-driven-development. The user approved the first-priority improvements and requested continuous implementation in the existing application workspace.

**Goal:** Keep Chrome open across GUI searches, retain the collector's dedicated profile across restarts, and preserve the active collection budget while a person completes verification.

**Architecture:** A single GUI worker owns a lazy browser pool for the lifetime of the application. Visible and headless Chrome use separate dedicated profiles under LocalAppData, guarded by OS file locks. Runner, browser provider, and downloader share an active deadline. Manual verification has a separate cumulative 600-second allowance per keyword. Three consecutive missing Google originals stop the engine and save bounded local diagnostics.

**Constraints:** Python 3.10+, Windows/Tk/Selenium; no changes to saved collection-option schemas; no CAPTCHA bypass or interaction with existing blog Chrome profiles; no fixed debugging port; existing cancellation, resume, API, and selected-download behavior must remain intact. Work in the existing checkout per the user's instruction to continue through completion.

## Tasks

- [x] Add failing tests for same worker/session across separate GUI searches, persistent cookies across Chrome restarts, profile locking, and recovery after a window closes. Implement browser pool and GUI worker ownership, including shutdown.
- [x] Add failing tests for verification exceeding the active deadline, subsequent actual image download, cancellation and bounded manual waiting. Share an active budget and replace wall-clock Selenium waits with pause-aware polling.
- [x] Add failing tests for repeated original extraction failures and recovery/reset. Save bounded JSON and screenshot diagnostics, stop after three consecutive failures, and surface the reason in GUI and run records.
- [x] Run targeted and full tests using real local Chrome/HTTP/Tk, inspect the final diff, update version and usage documentation. Keep CAPTCHA mitigation claims limited to verified session behavior.

## Execution record

Baseline: 133 tests passed. New tests were first observed failing for missing profile/pool APIs, verification consuming the keyword deadline, missing diagnostic stop behavior, and missing driver cleanup/recovery. Final implementation passes 142 tests. The GUI integration exercises two separate actual runner invocations, local DOM extraction, PNG saving and gallery updates using the same Chrome session and worker thread. A fresh BrowserSession retains a persistent cookie after Chrome restarts. An independent final read-only review reported no actionable findings.

Ruling: automatic stop after three missing originals applies to original-only mode. Original-preferred mode retains its explicitly requested thumbnail fallback; image size and download transport rejection do not count as extraction failures.

Ruling: use the existing application checkout because the user requested continuous implementation in this workspace. No unrelated remote branch or browser profile is modified. Delivery in this task is local; no remote push is required by the current request.

Delivery update: after verifying version 2.1.1 and the size-threshold guidance, the user requested committing and pushing all accumulated changes. Use the previously confirmed default branch master, retain the existing branch name, and verify the remote commit after pushing.

## Review focus

- A second GUI search must run on the same owner thread and Chrome session.
- Closing Chrome manually must allow a new session using the same profile on the next task.
- Two application processes must not concurrently use one profile; failure must be actionable and must not delete Chrome profile locks.
- Manual verification must pause provider, detail-wait, runner, and download deadlines together and remain cancellable.
- Only consecutive missing originals trigger a diagnostic stop; size rejection or transport errors must not trigger it.
