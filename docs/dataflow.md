# Fieldnotes — Data Flow

**Version:** 1.0
**Date:** July 17, 2026
**Companions:** prd.md, techstack.md

---

## 1. Overview

Fieldnotes has two distinct data flows — **index time** and **question time** — plus a persistence layer both write into. The architecture's central claim is expressed entirely in what crosses the local/cloud boundary:

> Raw files, the index, embeddings, generated artifacts, and code execution never leave the student's machine. Only retrieved passages, dataset schemas/summaries, and the user's question are sent to the GPT-5.6 API; only intent classifications, generated code, and answer prose come back.

This is verifiable: a judge watching the network tab sees API calls carrying passages and schemas — never file contents or raw dataset rows.

---

## 2. Index-time flow (entirely local, one boundary crossing at the end)

```
Course folder ──► Parsers ──► Hybrid local index ──► Local storage ──► Workspace brief
(PDFs, decks,     (text +      (BM25 + deterministic  (SQLite +          (inventory →
 docs, CSVs)       anchors,     local embeddings)      embeddings)        starter cards)
                   CSV schemas)
```

### 2.1 Stages and the data produced at each

| Stage | Input | Output | Where it lives |
|---|---|---|---|
| Discovery | Selected folder path | Recursive file list (PDF, PPTX, DOCX, MD, TXT, CSV) | Memory → SQLite metadata |
| Parsing — documents | PDF/PPTX/DOCX bytes | Chunked text with anchors (page/block, slide number, paragraph index) | SQLite (chunks + anchors) |
| Parsing — tabular | CSV bytes | Schema (columns, dtypes, row counts), summary statistics, per-column outlier flags (z-score) | SQLite (dataset profiles) |
| Embedding | Text chunks | Deterministic local vectors | SQLite embeddings table |
| Keyword index | Text chunks | BM25 index | Serialized locally |
| Brief generation | **Inventory only** — file names, counts, schemas, summary stats | Course summary + 3–4 starter cards (one seeded by outlier flags when present) | Rendered in UI; cached in SQLite |

### 2.2 Boundary crossings at index time

Exactly **one**: brief generation sends the inventory (names, counts, schemas, stats) to GPT-5.6. Document content and raw rows are never transmitted. Embedding is local and deterministic, so semantic indexing stays on-device.

### 2.3 UI stream

Per-file progress and one-line comprehension summaries ("parsed pendulum.csv — 5 trials, 200 rows") stream to the UI over SSE throughout (F2, F3), ending with the workspace brief (F3).

---

## 3. Question-time flow (round-trip inventory)

### 3.1 Boundary diagram

```
┌─ Student's machine ────────────────────┐
│                                        │        passages + question
│   UI + trace      Local index         │  ───────────────────────────►   GPT-5.6 API
│   (3 panes, SSE)  (passage retrieval) │                                 (router, codegen,
│                                        │  ◄───────────────────────────    prose)
│   Sandbox         SQLite              │        intent, code, answers
│   (runs code      (notebook,          │
│    on CSVs)        concept log)       │
└────────────────────────────────────────┘
```

### 3.2 Worked trace — an `analyze` question

"Why does Trial 4 look different?"

| # | Step | Location | Data that moves | Trace strip shows |
|---|---|---|---|---|
| 1 | Intent classification | **Round trip 1** | Out: question + one-line workspace summary. Back: structured output `{intent: analyze, targets: [pendulum.csv], connect: true}` | `agent · analyze` |
| 2 | Retrieval | Local | Hybrid index returns theory passages (with anchors); SQLite returns the CSV's schema + summary stats | — |
| 3 | Code generation | **Round trip 2** | Out: question + schema/stats (columns, dtypes, distributions — **not raw rows**). Back: Python script | `wrote analysis.py` |
| 4 | Execution | Local | Sandbox runs the script against the actual CSV (timeout, memory cap, no network). Captured: computed values, stdout, matplotlib PNG. **The only place raw data is touched — entirely on-device** | `ran locally · 1.8s` |
| 5 | Grounding | **Round trip 3** | Out: computed results + retrieved passages. Back: explanation connecting anomaly to theory | `matched ch6_damping.pdf §6.3` |
| 6 | Persistence + display | Local | Answer streams to UI via SSE with citation chips; chart, script, and explanation written to SQLite as notebook artifacts; concept ("damping ratio") upserted into the concept log | — |

On sandbox failure, one automatic retry: the error message is fed back to GPT-5.6 with the original script (an extra instance of round trip 2).

### 3.3 Flow variants by intent

| Intent | Round trips | What differs |
|---|---|---|
| `retrieve` | 2 (classify, ground) | Skips codegen/execution; passages only |
| `analyze` / `visualize` | 3 (classify, codegen, ground) | Full worked trace above; `visualize` emphasizes the chart artifact |
| `connect` | 3 | Grounding call receives both a computed/dataset result and retrieved theory passages |
| `quiz` | 1 + 1 per question | Out: concept-log entries + their cited chunks. Back: one question per call. Grades written back locally |

### 3.4 Quiz loop closure

Quiz grades update concept states in SQLite (shaky = amber). Updated concept states regenerate the suggested starting points — closing Learn → Investigate → Understand → Practice (F7, F8).

---

## 4. Persistence layer (all local, survives restart)

| Store | Contents | Written by |
|---|---|---|
| SQLite | File metadata, chunk anchors, dataset profiles, concept log, quiz history, notebook artifact records | Indexer, agent pipeline, quiz grader |
| SQLite embeddings table | Chunk embeddings | Indexer |
| Workspace artifacts dir | Generated scripts (`analysis.py` per answer), chart PNGs | Sandbox |

Citation chips resolve locally: document chips → `GET /source/{file_id}/{anchor}?workspace_id=...`; code chips → the retained script + captured output via `GET /artifact/{id}?workspace_id=...` (F6, F9).

---

## 5. Data minimization summary

| Data class | Sent to GPT-5.6? |
|---|---|
| Raw files (PDF/PPTX/DOCX/CSV bytes) | Never |
| Full document text | Never — only retrieved passages relevant to the question |
| Raw dataset rows | Never where avoidable — schemas, dtypes, and summary statistics instead |
| Index / embeddings | Never — embeddings are computed locally |
| Concept log / quiz history | Only the concept names + their cited chunks, at quiz time |
| Question text | Yes (required for reasoning) |
| Computed analysis results | Yes, at grounding time (values, not the dataset) |

**Positioning:** local-first workspace, cloud reasoning. The reasoning call never receives the folder.

---

## 6. Streaming channels (SSE)

| Channel | Endpoint | Events |
|---|---|---|
| Indexing progress | `GET /index/events/{run_id}` | `file_started`, `file_parsed` (with comprehension line), `index_complete`, `brief_ready` |
| Router trace + answer | `POST /ask` (SSE response) | `intent`, `step` (retrieval / codegen / execution / grounding), `token` (answer prose), `artifact` (chart/script/explainer IDs), `citations`, `concepts`, `done` |

The router trace UI (F4) is a direct render of the `step` events. Frontend consumes SSE over fetch-stream parsing rather than `EventSource`.
