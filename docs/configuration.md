# Fieldnotes Configuration Reference

## Required

- No LLM credential is required for local startup

## Optional

- `OPENAI_API_KEY`: enables live Responses API mode automatically when present
- `OPENAI_MODEL`: defaults to `gpt-5`
- `FIELDNOTES_USE_FAKE_LLM`: `1` requests deterministic internal LLM stub when no API key is present
- `FIELDNOTES_RETRIEVAL_PROVIDER`: `bm25 | hybrid | vector`
- `FIELDNOTES_EMBEDDINGS_PROVIDER`: `deterministic`
- `FIELDNOTES_EMBEDDING_MODEL`: defaults to `hash-v1`
- `FIELDNOTES_BM25_WEIGHT`
- `FIELDNOTES_VECTOR_WEIGHT`
- `FIELDNOTES_MAX_RETRIEVAL_CANDIDATES`
- `FIELDNOTES_MAX_CONTEXT_CHUNKS`
- `FIELDNOTES_MAX_CONTEXT_TOKENS`
- `FIELDNOTES_ENABLE_TRACING`
- `FIELDNOTES_ENABLE_METRICS`
- `FIELDNOTES_VERBOSE_TRACING`
- `VITE_API_BASE_URL`: optional frontend override; leave empty for default local Vite proxy workflow

## Startup validation

Startup validates:

- Responses API configuration
- Workspace registry write permission
- SQLite write access
- Sandbox availability
- Retrieval and embedding provider names
- Optional live Responses API probe in Phase 0 when `OPENAI_API_KEY` is present

The backend loads project-root `.env` before validation. Existing shell variables take precedence over `.env` values.

## Startup mode selection

Priority order:

1. `OPENAI_API_KEY`
2. `FIELDNOTES_USE_FAKE_LLM=1`
3. automatic fallback to fake mode

Behavior:

- `OPENAI_API_KEY` present: startup uses live OpenAI mode automatically
- no API key and `FIELDNOTES_USE_FAKE_LLM=1`: startup uses fake mode
- no API key and no fake flag: startup still succeeds and falls back to fake mode

Startup logs:

- live mode: `INFO: OpenAI API detected. Running in live mode.`
- explicit fake mode: `INFO: Running in fake LLM mode.`
- automatic fallback:
  - `WARNING: No OPENAI_API_KEY detected.`
  - `WARNING: Falling back to fake LLM mode.`
  - `WARNING: Set OPENAI_API_KEY to enable live OpenAI responses.`

## Workspace registry

- Location: `.fieldnotes_registry/workspaces.json`
- Backup: `.fieldnotes_registry/workspaces.backup.json`
- Corruption quarantine: `.fieldnotes_registry/workspaces.corrupt-YYYY-MM-DDTHHMMSSZ.json`
- Recovery behavior: malformed, truncated, empty, unreadable, or invalid registry files are quarantined when possible, replaced with a fresh empty registry, and logged as warnings
- Health diagnostic: `/health` includes `registry_warning` when automatic recovery occurred during current process lifetime

## Workspace storage repair

- Workspace database: `<workspace>/.fieldnotes/fieldnotes.db`
- Quarantine names: `fieldnotes.db.corrupt-YYYY-MM-DDTHHMMSSZ`, plus matching `-wal` and `-shm` sidecars when present
- Integrity validation: each database open runs `PRAGMA integrity_check`
- Repair flow:
  - checkpoint WAL
  - reopen and re-run integrity check
  - quarantine damaged files if still broken
  - create replacement database
  - rebuild from source files when available
  - rehydrate file-backed artifact metadata from `.fieldnotes/artifacts/`
- Health diagnostic: `/health` includes `storage_warning` after repair or recreate events during current process lifetime

## Live verification

Phase 0 includes optional end-to-end live Responses API verification through `scripts/exit_phase0.py`.

- Enabled when `OPENAI_API_KEY` is set
- Uses configured `OPENAI_MODEL`; no model name is hardcoded in probe
- Sends one tiny prompt and expects strict JSON `{"status":"ok"}`
- Expected runtime: usually a few seconds
- Expected cost: minimal, single tiny request
- CI behavior: missing credentials reports `LIVE API ... SKIPPED` and does not fail
- Why optional: most CI and offline setups should not require live billing credentials

## Cross-platform notes

- Windows: sandbox uses native Job Object limits for CPU time, memory, process count, and cleanup
- macOS / Linux: sandbox uses `resource.setrlimit` for CPU, memory, process count, and file descriptor caps
- Paths with spaces and Unicode are supported
