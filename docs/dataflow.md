# Fieldnotes Data Flow

**Version:** `1.0.0-beta.1`
**Status:** shipped beta runtime

## Indexing

```text
workspace folder
  -> discovery (PDF, PPTX, DOCX, MD, TXT, CSV)
  -> parse / normalize / profile CSV
  -> deterministic chunking and anchors
  -> SQLite persistence and migration bootstrap
  -> deterministic local embeddings
  -> local workspace brief
  -> run-scoped indexing SSE events
```

`POST /index` registers a stable workspace ID and returns a run ID. The caller consumes only `GET /index/events/{run_id}` for that run. Events are `file_started`, `file_parsed`, `index_complete`, and `brief_ready`. Indexing failures are reported as parse status or an event-stream error; a failed embedding does not fail the indexing run.

Each workspace owns `<workspace>/.fieldnotes/fieldnotes.db` and `<workspace>/.fieldnotes/artifacts/`. Workspace registry metadata is persisted separately under `.fieldnotes_registry/workspaces.json`, with `.fieldnotes_registry/workspaces.backup.json` retained as latest known-good backup. Corrupted registry files are quarantined under `.fieldnotes_registry/workspaces.corrupt-*.json` before an empty registry is recreated. Database bootstrap applies additive migrations on open. File and chunk IDs are deterministic; request and run IDs are UUID-based.

## Ask

```text
question + workspace_id
  -> intent classification
  -> configured local retrieval
  -> candidate reranking and context budget
  -> planner / sequential executor when applicable
  -> optional local sandbox analysis and artifact persistence
  -> grounded answer generation
  -> ask SSE events
```

Retrieval uses BM25, local vector search, or hybrid fusion, selected by configuration. It returns persisted chunks with relative path, anchor, file ID, score, and internal diagnostics. Reranking removes duplicate or overlapping chunks and enforces file-diverse context limits before any answer grounding.

In live mode, the backend calls the OpenAI Responses API for structured intent, planning, quiz, and grounded-answer operations. It sends only the question, retrieved chunks, permitted profiles, and computed local results. Fake mode makes no external call and produces deterministic, retrieved-content-only answers, including metadata answers such as workspace file counts and document lists.

`POST /ask` streams `intent`, `step`, `token`, `artifact`, `citations`, `concepts`, and `done`; on failure it emits `error` then closes. Citations always point to persisted chunk anchors. A source is reopened through `GET /source/{file_id}/{locator}?workspace_id=...`.

## Quiz and notebook

```text
retrieved workspace chunks
  -> grounded quiz question
  -> persisted attempt
  -> grading and concept update
  -> quiz-result artifact
```

`POST /quiz` and `/quiz/start` stream a grounded question. `POST /quiz/answer` streams `graded` then `quiz_done`, updates concept state, and persists a quiz-result artifact. Notebook cards and artifact payloads are loaded through `/notebook` and `/artifact/{artifact_id}`.

## Local-first boundary

| Data | Leaves the machine in live mode? |
|---|---|
| Raw source bytes and complete files | No |
| SQLite database, chunks, embeddings, artifacts, quiz history | No |
| Full CSV rows | No; local profiles and computation are used instead |
| Retrieved passages, user question, permitted profiles, computed results | Yes, when needed for a live Responses API call |
| Fake-mode data | No |
