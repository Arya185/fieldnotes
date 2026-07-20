# Fieldnotes

Fieldnotes `1.0.0-beta.1` is local-first AI learning workspace for course folders. Backend indexes course files into local SQLite + retrieval stores. Frontend exposes chat, notebook, quiz, source viewer, developer diagnostics. RC1 hardens release path without changing public APIs.

## Capabilities

- Local indexing for `pdf`, `pptx`, `docx`, `md`, `txt`, `csv`
- Grounded chat over persisted chunks with citations
- Quiz generation and grading from workspace content
- Notebook artifact persistence for explainers, scripts, charts, quiz results
- Source reopening by persisted anchor
- Release smoke verification and benchmark tooling

## Version

- Release: `1.0.0-beta.1`
- Backend version source: `backend/config.py`
- Frontend version source: `frontend/package.json`

## Installation Guide

Backend:

```bash
python -m venv .venv312
```

macOS / Linux:

```bash
. .venv312/bin/activate
python -m pip install -r backend/requirements.txt
```

Windows PowerShell:

```powershell
.venv312\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
```

Frontend:

```bash
cd frontend
npm install
```

Required environment:

Environment example:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-5
```

Optional fake mode in `.env`:

```bash
FIELDNOTES_USE_FAKE_LLM=1
```

## Beta Onboarding

Start with [docs/beta-onboarding.md](/Users/aryapatel/arya/Programming/All Hackathons/Fieldnotes/docs/beta-onboarding.md). It is single path for external beta users and points to install, demo workflow, feedback template, known issues, and release notes.

## Quick Start

Start backend:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Start frontend dev server:

```bash
cd frontend
npm run dev
```

Vite dev server proxies API requests to `http://127.0.0.1:8000` by default. No `VITE_API_BASE_URL` needed for local development.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Run release smoke:

```bash
python scripts/release_check.py
```

`run.sh` is Unix helper only. On Windows, start backend and frontend with direct `python` / `npm` commands above.

## Developer Guide

- Backend entrypoint: `backend/main.py`
- Retrieval/indexing: `backend/indexer/`
- Agent planner/executor: `backend/agent/`
- Sandbox: `backend/sandbox/`
- Observability: `backend/telemetry/tracing.py`
- Frontend shell: `frontend/src/App.tsx`
- Contracts: `docs/schemas.md`
- Release checks: `scripts/release_check.py`
- Benchmarks: `scripts/run_benchmarks.py`

Run checks:

```bash
python -m unittest discover -s tests
cd frontend && npm test
cd frontend && npm run build
python scripts/run_benchmarks.py
python scripts/release_check.py
```

## Documentation Index

- [Installation guide](docs/installation.md)
- [Quick start](docs/quickstart.md)
- [Developer guide](docs/developer-guide.md)
- [Architecture overview](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Configuration reference](docs/configuration.md)
- [Beta onboarding](docs/beta-onboarding.md)
- [Beta feedback template](docs/beta-feedback-template.md)
- [Beta known issues](docs/beta-known-issues.md)
- [Release notes](docs/release-notes-1.0.0-beta.1.md)

## Sample Workspace

`demo_course/` contains:

- `pendulum_summary.pdf`
- `notes.md`
- `pendulum.csv`

Use it to exercise indexing, retrieval, notebook, quizzes, source viewer.
