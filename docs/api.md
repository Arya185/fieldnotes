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

Example:

Request:

```json
{"folder_path":"/Users/student/course/demo_course"}
```

Response:

```json
{"status":"accepted","workspace_id":"86e6c3e1-cb6a-4cef-b8a0-695b325126bb","run_id":"run_123","events":"/index/events/run_123"}
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

Example request:

```json
{"workspace_id":"86e6c3e1-cb6a-4cef-b8a0-695b325126bb","question":"Why does Trial 4 look different?"}
```

Example SSE sequence:

```text
data: {"event":"intent","answer_id":"answer_123","intent":"analyze","targets":[],"connect":true}
data: {"event":"step","answer_id":"answer_123","step":"retrieval","label":"searching selected workspace","status":"started","duration_ms":null,"file_id":null}
data: {"event":"step","answer_id":"answer_123","step":"retrieval","label":"retrieved 5 passages","status":"ok","duration_ms":null,"file_id":null}
data: {"event":"step","answer_id":"answer_123","step":"grounding","label":"grounding answer in retrieved passages","status":"started","duration_ms":null,"file_id":null}
data: {"event":"token","answer_id":"answer_123","text":"Grounded answer for Why does Trial 4 look different?"}
data: {"event":"artifact","answer_id":"answer_123","artifact_id":"artifact_123","kind":"explainer","title":"Answer: Why does Trial 4 look different?","url":"/artifact/artifact_123"}
data: {"event":"citations","answer_id":"answer_123","chips":[{"chip_type":"document","label":"notes.txt (block1/b1)","anchor":"file_alpha#block1/b1","artifact_id":null}]}
data: {"event":"concepts","answer_id":"answer_123","updates":[{"concept_id":"concept_grounding","name":"grounding","state":"touched"}]}
data: {"event":"done","answer_id":"answer_123"}
```

## Quiz

### `POST /quiz/start`

Both routes start one grounded question.

```json
{"workspace_id":"...","concept_ids":["grounding"]}
```

`concept_ids` may be `null`. The stream emits `question` or `error`. A `question` includes `attempt_id`, `index`, `total`, four `options`, `source_label`, and `source_anchor`.

Example request:

```json
{"workspace_id":"86e6c3e1-cb6a-4cef-b8a0-695b325126bb","concept_ids":["grounding"]}
```

Example SSE response:

```text
data: {"event":"question","attempt_id":"attempt_123","index":1,"total":1,"question":"Which file contains the grounded concept?","options":["alpha.txt","beta.txt","gamma.txt","delta.txt"],"source_label":"notes.txt block1/b1","source_anchor":"file_alpha#block1/b1"}
```

### `POST /quiz/answer`

```json
{"workspace_id":"...","attempt_id":"...","chosen_index":0}
```

The stream emits `graded` then `quiz_done`, or `error`. `graded` includes the correctness result, explanation, citation chip, and concept update. `quiz_done` includes score, total, `artifact_id`, and refreshed starter cards.

Example request:

```json
{"workspace_id":"86e6c3e1-cb6a-4cef-b8a0-695b325126bb","attempt_id":"attempt_123","chosen_index":0}
```

Example SSE sequence:

```text
data: {"event":"graded","attempt_id":"attempt_123","is_correct":true,"correct_index":0,"explanation":"Correct. The answer matches the grounded source passage.","chip":{"chip_type":"document","label":"notes.txt block1/b1","anchor":"file_alpha#block1/b1","artifact_id":null},"concept_update":{"concept_id":"concept_grounding","name":"grounding","state":"touched"}}
data: {"event":"quiz_done","score":1,"total":1,"artifact_id":"artifact_quiz_123","refreshed_starters":[{"text":"Investigate anomalous damping pattern","file_path":"notes.txt","seed":"anomaly"},{"text":"Review grounded concept connections","file_path":"notes.txt","seed":"concept"},{"text":"Practice with quiz follow-up","file_path":"notes.txt","seed":"practice"}]}
```

## Notebook and Sources

### `GET /notebook?workspace_id=...`

Returns `{ "artifacts": [...] }`. Every card has `id`, `kind` (`chart`, `explainer`, `quiz_result`, or `script`), `title`, `created_at`, and optional `url`.

Example response:

```json
{
  "artifacts": [
    {
      "id": "artifact_123",
      "kind": "explainer",
      "title": "Answer: Why does Trial 4 look different?",
      "created_at": "2026-07-20T21:30:58.154326+00:00",
      "url": "/artifact/artifact_123"
    }
  ]
}
```

### `GET /artifact/{artifact_id}?workspace_id=...`

Returns an artifact file when one exists, otherwise JSON with `id`, `kind`, `title`, and `payload_text`.

### `GET /source/{file_id}/{locator}?workspace_id=...`

Returns the persisted chunk for a citation anchor:

```json
{"text":"...","label":"notes.md paragraph:1","file_path":"notes.md"}
```

Example response:

```json
{
  "text": "Trial 4 damping explanation",
  "label": "notes.txt block1/b1",
  "file_path": "notes.txt"
}
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
