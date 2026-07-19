# Fieldnotes Troubleshooting

## `OPENAI_API_KEY is required unless FIELDNOTES_USE_FAKE_LLM=1`

Set `OPENAI_API_KEY` for live mode, or set `FIELDNOTES_USE_FAKE_LLM=1` for offline smoke and CI.

## `Unknown FIELDNOTES_RETRIEVAL_PROVIDER`

Allowed values:

- `bm25`
- `hybrid`
- `vector`

## `Sandbox availability check failed`

- Verify Python executable exists
- Verify process can write temp files
- Verify local environment supports subprocess execution
- On Windows, backend supports sandbox subprocess execution but not Unix `resource` limits

## `Unknown workspace_id`

Index workspace first. `/ask`, `/quiz`, `/notebook`, `/source` require persisted workspace registration.

## Frontend build failure

Run:

```bash
cd frontend
npm install
npm run build
```

## Windows startup

- `run.sh` does not work on Windows
- Use `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`
- Use `npm run dev` in `frontend/`
