# Fieldnotes API Reference

**Version:** `1.0.0-beta.1`
**Base URL:** `http://127.0.0.1:8000`

The backend is a local FastAPI service. JSON requests use `application/json`. Streaming endpoints return Server-Sent Event frames as `data: <json>\n\n`.

## Health

### `GET /health`

Returns startup status.

```json
{"status":"ok","version":"1.0.0-beta.1","mode":"fake","startup":"healthy"}
```

`mode` is resolved at startup:

- `live` when `OPENAI_API_KEY` is present
- `fake` when `FIELDNOTES_USE_FAKE_LLM=1`
- `fake` when no API key is present and startup falls back automatically

`/health` may also include `registry_warning` and `storage_warning` when automatic recovery occurred during current process lifetime.

## Indexing

### `POST /index`

```json
{"folder_path":"/absolute/path/to/workspace"}
```

Returns `202 Accepted`:

```json
{"status":"accepted","workspace_id":"...","run_id":"...","events":"/index/events/..."}
```

### `GET /index/events/{run_id}`

Streams `file_started`, `file_parsed`, `index_complete`, then `brief_ready`. `file_parsed` has `file_id`, `display_name`, `parse_status` (`parsed`, `failed`, or `skipped`), and `parse_summary`.

## Grounded Chat

### `POST /ask`

```json
{"workspace_id":"...","question":"Why does Trial 4 look different?"}
```

Streams `intent`, zero or more `step` and `token` events, zero or more `artifact` events, then `citations`, `concepts`, and `done`. A failed stream emits `error` and terminates. All answer events include `answer_id`.

- `intent`: `intent` is one of `retrieve`, `analyze`, `visualize`, `connect`, `quiz`; includes `targets` and `connect`.
- `step`: `step` is `retrieval`, `codegen`, `execution`, `grounding`, or `retry`; includes `label`, `status`, optional `duration_ms`, and optional `file_id`.
- `citations`: `chips` contain document anchors or artifact IDs.
- `concepts`: updates have `concept_id`, `name`, and `state` (`touched` or `shaky`).

## Quiz

### `POST /quiz` and `POST /quiz/start`

Both routes start one grounded question.

```json
{"workspace_id":"...","concept_ids":["grounding"]}
```

`concept_ids` may be `null`. The stream emits `question` or `error`. A `question` includes `attempt_id`, `index`, `total`, four `options`, `source_label`, and `source_anchor`.

### `POST /quiz/answer`

```json
{"workspace_id":"...","attempt_id":"...","chosen_index":0}
```

The stream emits `graded` then `quiz_done`, or `error`. `graded` includes the correctness result, explanation, citation chip, and concept update. `quiz_done` includes score, total, `artifact_id`, and refreshed starter cards.

## Notebook and Sources

### `GET /notebook?workspace_id=...`

Returns `{ "artifacts": [...] }`. Every card has `id`, `kind` (`chart`, `explainer`, `quiz_result`, or `script`), `title`, `created_at`, and optional `url`.

### `GET /artifact/{artifact_id}?workspace_id=...`

Returns an artifact file when one exists, otherwise JSON with `id`, `kind`, `title`, and `payload_text`.

### `GET /source/{file_id}/{locator}?workspace_id=...`

Returns the persisted chunk for a citation anchor:

```json
{"text":"...","label":"notes.md paragraph:1","file_path":"notes.md"}
```

## Errors

REST errors return stable JSON:

```json
{
  "code": "WORKSPACE_NOT_FOUND",
  "message": "Selected workspace was not found.",
  "recoverable": true,
  "request_id": "req_..."
}
```

SSE errors emit one final `error` event with:

```json
{
  "event": "error",
  "answer_id": "answer_...",
  "code": "SANDBOX_ERROR",
  "message": "Local analysis failed to complete safely.",
  "recoverable": true,
  "request_id": "req_..."
}
```

Stable public error codes:

- `INVALID_REQUEST`
- `WORKSPACE_NOT_FOUND`
- `LIVE_API_UNAVAILABLE`
- `MODEL_CONFIGURATION_ERROR`
- `SANDBOX_ERROR`
- `DATABASE_ERROR`
- `TIMEOUT`
- `INTERNAL_ERROR`

Unknown workspaces, runs, artifacts, and source anchors use stable error objects rather than raw internal exceptions. Startup no longer fails when `OPENAI_API_KEY` is absent; runtime falls back to fake mode as documented in [configuration.md](configuration.md).
