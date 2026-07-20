# Fieldnotes Implementation Phases

**Version:** `1.0.0-beta.1`
**Status:** historical build plan reconciled to the shipped beta

This document records delivered capability, not a future implementation contract. Public API details live in [api.md](api.md); event and model contracts live in [schemas.md](schemas.md).

| Phase | Delivered status | Evidence |
|---|---|---|
| 0 - configuration and documentation | Complete | `scripts/exit_phase0.py` verifies configuration, startup, health, fake mode, live missing-key validation, and Responses configuration. |
| 1 - indexing foundation | Complete | Stable workspaces, migration-aware SQLite bootstrap, parsers, chunking, CSV profiles, local embeddings, retrieval, `/index`, and index SSE. `scripts/exit_phase1.py` exercises the workflow. |
| 2 - grounded agent | Complete | Responses API client, deterministic fake client, planner/executor, local sandbox, artifacts, reranking, and internal diagnostics. |
| 3 - workspace frontend | Complete | React workspace, streaming chat, citations/source viewer, notebook, quiz, empty/error states, and developer diagnostics. |
| 4 - study loop | Complete | Workspace brief, grounded quizzes, concept updates, artifact persistence, and source reopening. |
| 5 - release hardening | In progress | Cross-platform scripts, release check, benchmark runner, beta documentation, and known-issue tracking are present. Packaging and external-beta validation remain release work. |
| 6 - public submission | Not started | External release and submission activities are outside the repository runtime. |

## Current verification

```bash
python scripts/exit_phase0.py
python scripts/exit_phase1.py
python -m unittest discover -s tests
cd frontend && npm test && npm run build
python scripts/run_benchmarks.py
python scripts/release_check.py
```

The Phase 0 verifier is portable Python. `scripts/exit_phase0.sh` remains a legacy Unix wrapper. Release verification requires a Python environment that can discover npm on `PATH`. When `OPENAI_API_KEY` is present, Phase 0 performs one live Responses API probe against configured model; otherwise that step is reported as skipped.

GitHub Actions keeps fake-mode release validation on every push and pull request. Separate live OpenAI validation job runs only when `OPENAI_API_KEY` secret is available, then executes Phase 0 live probe and `tests.test_live_responses_api_integration` against configured live model. Missing secret skips live job without failing workflow.
