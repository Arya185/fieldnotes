# Fieldnotes Progress Tracker

**Version:** `1.0.0-beta.1`
**Last reconciled:** 2026-07-21

## Status dashboard

| Phase | Scope | Status | Evidence |
|---|---|---|---|
| 0 | Configuration, startup, contract documentation | ✅ complete | `scripts/exit_phase0.py` PASS: configuration, startup, health, fake mode, live validation, Responses configuration. |
| 1 | Workspace indexing and persistence | ✅ complete | `scripts/exit_phase1.py` PASS; indexing, retrieval, ask, quiz, artifacts, citation integrity, and source reopening are exercised. `backend/main.py` now exposes `get_workspace_manager()` and `get_run_manager()` dependency providers, so workspace and run state can be overridden in tests without changing route behavior. |
| 2 | Local retrieval and grounded execution | ✅ complete | BM25/vector/hybrid retrieval, reranking, planner/executor, local sandbox, artifacts, telemetry, and regression coverage are in runtime. Retrieval-quality evaluation is wired through `tests/fixtures/demo_course_retrieval_eval.json` and `scripts/run_benchmarks.py`, reporting precision/recall/MRR against labeled `demo_course/` queries. |
| 3 | Production frontend | ✅ complete | React workspace, streaming chat, citations, notebook, quiz, source viewer, and developer diagnostics are implemented. |
| 4 | Study loop | ✅ complete | Briefs, quiz attempts, concept updates, notebook artifacts, and citation reopening are persisted. |
| 5 | Release hardening and beta validation | 🟡 in progress | Release and benchmark scripts, demo workspace, onboarding, troubleshooting, and known issues exist. Cross-platform release verification and external beta evidence remain. |
| 6 | Public submission | ⬜ not started | Not a repository implementation task. |

## Verification record

| Date | Command | Result |
|---|---|---|
| 2026-07-21 | `FIELDNOTES_USE_FAKE_LLM=1 python -m unittest discover -s tests` | `Ran 135 tests in 45.681s` / `OK (skipped=4)` |
| 2026-07-20 | `.venv312/bin/python -m unittest discover -s tests` | PASS |
| 2026-07-20 | `cd frontend && npm test` | PASS |
| 2026-07-20 | `cd frontend && npm run build` | PASS |
| 2026-07-20 | `.venv312/bin/python scripts/exit_phase0.py` | PASS (7 checks, live probe skipped without credentials) |
| 2026-07-20 | `.venv312/bin/python scripts/exit_phase1.py` | PASS (10 checks) |

## Open release work

- Validate `scripts/release_check.py` in a Python environment where npm is discoverable on `PATH`.
- Complete external beta feedback and platform evidence before declaring a stable `1.0.0` release.

No completed implementation phase is marked as not started.
