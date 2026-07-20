# Fieldnotes Troubleshooting

## Startup mode looks wrong

Startup mode priority is:

1. `OPENAI_API_KEY`
2. `FIELDNOTES_USE_FAKE_LLM=1`
3. automatic fallback to fake mode

If `OPENAI_API_KEY` is absent, startup does not fail. Backend logs warning and falls back to fake mode. Existing shell variables still override project-root `.env`.

## `Unknown FIELDNOTES_RETRIEVAL_PROVIDER`

Allowed values:

- `bm25`
- `hybrid`
- `vector`

## `Sandbox availability check failed`

- Verify Python executable exists
- Verify process can write temp files
- Verify local environment supports subprocess execution
- On Windows, sandbox uses native Job Object containment rather than Unix `resource` limits

## `Unknown workspace_id`

Index workspace first. `/ask`, `/quiz`, `/notebook`, `/source` require persisted workspace registration. Public API returns stable error code `WORKSPACE_NOT_FOUND`.

If the workspace registry was auto-recovered, `/health` includes `registry_warning`. Existing workspace IDs may need to be recreated by indexing the workspace again.

## Public error responses

REST and SSE error payloads expose stable fields only:

- `code`
- `message`
- `recoverable`
- `request_id`

Backend logs keep full exception type and traceback for diagnostics.

## Manual workspace registry recovery

Registry files live under `.fieldnotes_registry/`:

- active registry: `workspaces.json`
- last known-good backup: `workspaces.backup.json`
- quarantined corrupt copies: `workspaces.corrupt-*.json`

Manual recovery steps:

1. Stop backend.
2. Inspect latest `workspaces.corrupt-*.json` and `workspaces.backup.json`.
3. Restore `workspaces.backup.json` to `workspaces.json` if it contains expected workspace IDs.
4. If no good registry remains, restart backend and re-index affected workspaces.

## Workspace storage repair

Workspace database files live under `<workspace>/.fieldnotes/`:

- `fieldnotes.db`
- `fieldnotes.db-wal`
- `fieldnotes.db-shm`
- quarantined copies: `fieldnotes.db.corrupt-*`, `fieldnotes.db-wal.corrupt-*`, `fieldnotes.db-shm.corrupt-*`

Repair behavior:

1. open database
2. run `PRAGMA integrity_check`
3. attempt WAL checkpoint and reopen once
4. if still corrupt, quarantine damaged files
5. create replacement database
6. rebuild from source files when available
7. restore file-backed artifact metadata from `.fieldnotes/artifacts/`

If no source files remain, public API returns stable message: `Workspace storage requires re-indexing.`

Manual recovery steps:

1. Stop backend.
2. Inspect newest quarantined database files in `.fieldnotes/`.
3. Restore source files if they were removed.
4. Restart backend and re-index workspace.
5. If needed, recover file-backed artifacts from `.fieldnotes/artifacts/`.

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
