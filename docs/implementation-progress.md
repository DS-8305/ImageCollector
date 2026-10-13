# Implementation ledger

Plan: docs/superpowers/plans/2026-10-13-google-image-collector.md
Base: 7be44cf. User authorized continuous implementation through final stage.
Execution: stable shared contracts first; independent modules can be delegated without overlapping file ownership; root integrates and independently reviews at finish.
Preflight: model -> downloader/provider/store/runner -> GUI/CLI. Output and exception interfaces fixed by plan; no shared mutable files assigned to workers.
Scope: all committed design stages including combined engines, resume/retry, gallery and optional configured API; image-recognition research features are not promised.
Task 1 complete: legacy baseline 20 and profiles 5 GREEN.
Task 2 complete: generated images/local HTTP download tests, hash contract aligned with recovery.
Task 3 complete: browser/API providers and real local Chrome; actual Naver payload observed, Google verification block recorded.
Task 4 complete: atomic journal, safe files, OS lock, both engines, stop/resume and persisted selections.
Task 5 complete: CLI, Korean GUI, candidate preview/selection, saved gallery/export, compatibility adapters.
Independent review complete: six material findings reproduced and fixed with RED-to-GREEN tests. Detailed report and dispositions in docs/verification.md.
Final suite: 129/129 PASS; compileall PASS; real Naver 3/3 saved; real Google needs_attention, no false success. External API actual account calls not made.
Task 6 complete: packaging documentation and launcher, clean diff, source commit 4e2e98a and pushed branch codex/google-image-collector.
Reviewable draft PR: https://github.com/DS-8305/ImageCollector/pull/2. No merge performed. Google live verification limitation is explicit in README, verification report and PR.
Follow-up: user Google runs skipped 30/55 candidates with missing original URLs. Added alternative detail image attributes and live skip/failure logs. Real Chrome/local HTTP integration saves two 1200x800 original PNGs with metadata. Full suite 132 PASS; user live retry remains needed because the diagnostic Google sessions were verification-blocked. See docs/google-download-fix.md.
Resolved follow-up: the running GUI predated the source fix. Added 2.0.1 to CLI/GUI title; a fresh user process saved 3 actual Google originals (2328x3160, 1200x940, 1200x1842). Decoding, metadata and pixel hashes verified. Final suite 132 PASS in 27.893s. Local first-failure capture launcher is verified and remains an uncommitted diagnostic aid.
Master delivery requested and authorized. CI exposed a preferred-fallback path after a retry could not fit the time budget. Deterministic RED-to-GREEN regression added; budget rejection now bypasses fallback. Final suite 133 PASS in 27.327s; installation instructions use default master.
