# Fieldnotes Quick Start

## Start backend

```bash
cp .env.example .env
```

Edit `.env`:

```bash
OPENAI_API_KEY=your_key
```

No API key required for local startup. If `OPENAI_API_KEY` is absent, Fieldnotes starts automatically in fake mode. Adding `OPENAI_API_KEY` switches startup to live OpenAI automatically.

Then start backend:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

## Start frontend dev server

```bash
cd frontend
npm run dev
```

The dev server proxies `/index`, `/ask`, `/quiz`, `/notebook`, `/artifact`, `/source`, `/health`, and `/openapi.json` to `http://127.0.0.1:8000`.

## Production build check

```bash
cd frontend
npm run build
```

## Run demo workflow

1. Index `demo_course/`
2. Ask `Why does Trial 4 look different?`
3. Start quiz
4. Open notebook artifact
5. Open source citation

On Windows, use PowerShell or Command Prompt for commands above. Do not use `run.sh`.

## Automated smoke

Phase 0 configuration and startup verification:

```bash
python scripts/exit_phase0.py
```

With `OPENAI_API_KEY` set, Phase 0 also runs one live Responses API probe against configured `OPENAI_MODEL`. Without credentials, startup still uses fake mode automatically, and Phase 0 reports `LIVE API ... SKIPPED`.

Full Phase 1 workflow verification:

```bash
python scripts/exit_phase1.py
```

Release verification:

```bash
python scripts/release_check.py
```

For full external beta flow, use [beta-onboarding.md](/Users/aryapatel/arya/Programming/All Hackathons/Fieldnotes/docs/beta-onboarding.md).
