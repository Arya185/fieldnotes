# Fieldnotes Developer Guide

## Repository structure

- `backend/main.py`: FastAPI endpoints
- `backend/config.py`: runtime validation, release metadata
- `backend/indexer/`: discovery, parsing, chunking, deterministic embeddings, retrieval
- `backend/agent/`: planner, executor, LLM integration
- `backend/sandbox/`: local Python execution
- `backend/storage.py`: persistence helpers
- `frontend/src/App.tsx`: production frontend shell
- `frontend/src/lib/api.ts`: fetch-based SSE client and API requests
- `frontend/vite.config.ts`: local dev proxy to backend
- `scripts/run_benchmarks.py`: benchmark runner
- `scripts/release_check.py`: RC verification
- `scripts/exit_phase0.py`: portable configuration/startup verifier
- `scripts/exit_phase1.py`: end-to-end local workflow verifier

## Local checks

```bash
python -m unittest discover -s tests
python scripts/exit_phase0.py
python scripts/exit_phase1.py
cd frontend && npm test
cd frontend && npm run build
python scripts/run_benchmarks.py
python scripts/release_check.py
```

## Release artifacts

- `scripts/benchmarks_latest.json`
- `scripts/release_artifacts/release_benchmarks.json`
- `scripts/release_artifacts/release_check_summary.json`

## Platform notes

- `run.sh` is Unix-only convenience wrapper.
- CI release workflow runs on Ubuntu, macOS, and Windows.
- Sandbox resource limits use native Windows Job Objects on Windows and `resource.setrlimit` on Unix platforms.

## Development workflow

1. Start backend on `127.0.0.1:8000`.
2. Start frontend with `cd frontend && npm run dev`.
3. Vite proxies backend API routes automatically. No manual base URL editing after clone.

## Dependency hygiene

- Backend manifest intentionally keeps only runtime dependencies used by shipped code paths.
- `npm install` currently reports audit findings. Do not force-upgrade blindly during beta if it risks behavior drift; review findings separately before stable release.
