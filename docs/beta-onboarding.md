# Fieldnotes Beta Onboarding

Version: `1.0.0-beta.1`

This beta package includes:

- `backend/`
- `frontend/`
- `demo_course/`
- published docs under `docs/`
- release notes: [release-notes-1.0.0-beta.1.md](/Users/aryapatel/arya/Programming/All Hackathons/Fieldnotes/docs/release-notes-1.0.0-beta.1.md)
- known issues: [beta-known-issues.md](/Users/aryapatel/arya/Programming/All Hackathons/Fieldnotes/docs/beta-known-issues.md)

## 1. Prerequisites

- Python 3.12
- Node.js 20+
- `OPENAI_API_KEY` for live beta evaluation

If you only need offline smoke verification, set `FIELDNOTES_USE_FAKE_LLM=1`.

## 2. Install

Follow [installation.md](/Users/aryapatel/arya/Programming/All Hackathons/Fieldnotes/docs/installation.md).

## 3. Start Fieldnotes

Backend:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm run dev
```

`run.sh` is Unix-only helper. Windows users should use commands above directly.

## 4. Recommended first-run workflow

1. Index `demo_course/`.
2. Wait for indexing to finish.
3. Ask: `Why does Trial 4 look different?`
4. Open citations from answer.
5. Start quiz for `grounding`.
6. Open notebook and review generated artifact.
7. Open source viewer from citation.

## 5. What to pay attention to

- Installation friction
- First indexing clarity
- Retrieval quality
- Answer quality
- Citation usefulness
- Notebook usefulness
- Quiz usefulness
- UI clarity
- Performance
- Bugs or crashes

## 6. Report feedback

Use [beta-feedback-template.md](/Users/aryapatel/arya/Programming/All Hackathons/Fieldnotes/docs/beta-feedback-template.md). Please include operating system, whether you used live mode or fake LLM mode, and exact steps to reproduce problems.

## 7. Before filing bug

- Check [troubleshooting.md](/Users/aryapatel/arya/Programming/All Hackathons/Fieldnotes/docs/troubleshooting.md)
- Check [beta-known-issues.md](/Users/aryapatel/arya/Programming/All Hackathons/Fieldnotes/docs/beta-known-issues.md)
- Run smoke check:

```bash
python scripts/release_check.py
```
