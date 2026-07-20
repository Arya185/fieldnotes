# Fieldnotes Installation Guide

Version: `1.0.0-beta.1`

## Prerequisites

- Python 3.12
- Node.js 20+
- `OPENAI_API_KEY` for live Responses API mode

## Backend install

Create venv:

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

## Frontend install

```bash
cd frontend
npm install
```

## Required environment

```bash
cp .env.example .env
```

Edit `.env` and set:

```bash
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-5
```

Optional fake mode in `.env`:

```bash
FIELDNOTES_USE_FAKE_LLM=1
```

This bypasses live OpenAI calls for CI, release smoke, and offline local verification. Use live mode with `OPENAI_API_KEY` for beta feedback on retrieval and answer quality.

Optional live production validation:

```bash
python scripts/exit_phase0.py
python -m unittest tests.test_live_responses_api_integration
```

Without `OPENAI_API_KEY`, live integration test is skipped and Phase 0 reports `LIVE API ... SKIPPED`.

GitHub Actions mirrors this split:

- fake-mode workflow runs on every push and pull request without secrets
- optional live OpenAI job runs only when repository secret `OPENAI_API_KEY` is available
- live job uses configured `OPENAI_MODEL` when set, otherwise normal application default applies
- expected runtime: usually under 1 minute
- expected cost: minimal, one tiny probe plus one tiny integration request
- optional by design so normal CI stays deterministic and secret-free

No manual `export` is required for normal local development. Backend loads project-root `.env` automatically.

Copy example config if you want one place to record settings:

```bash
cp .env.example .env
```

## Startup

Backend:

```bash
python -m uvicorn backend.main:app
```

Frontend:

```bash
cd frontend
npm run dev
```

Frontend development uses Vite proxying. API requests from `npm run dev` are forwarded to `http://127.0.0.1:8000` automatically. Leave `VITE_API_BASE_URL` empty for default local development.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Note: `run.sh` is Unix-only helper. Windows should start backend and frontend directly.

For external beta flow, continue with [beta-onboarding.md](/Users/aryapatel/arya/Programming/All Hackathons/Fieldnotes/docs/beta-onboarding.md).
