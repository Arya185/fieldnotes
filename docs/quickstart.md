# Fieldnotes Quick Start

## Start backend

```bash
cp .env.example .env
```

Edit `.env`:

```bash
OPENAI_API_KEY=your_key
```

Then start backend:

```bash
python -m uvicorn backend.main:app
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

```bash
python scripts/release_check.py
```

For full external beta flow, use [beta-onboarding.md](/Users/aryapatel/arya/Programming/All Hackathons/Fieldnotes/docs/beta-onboarding.md).
