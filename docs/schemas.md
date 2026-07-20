# Fieldnotes — Schemas

**Version:** `1.0.0-beta.1`
**Date:** July 20, 2026
**Companions:** prd.md, techstack.md, dataflow.md, design.md

This document is the single source of truth for every data shape two components must agree on: the SQLite database, the SSE event contract between backend and frontend, the Responses API structured-output schemas, and the dataset profile that forms the data-minimization boundary. Codex sessions build against these contracts; do not invent shapes elsewhere.

Conventions: all IDs are lowercase UUID4 strings unless noted; all timestamps are ISO 8601 UTC strings (`created_at TEXT`); all enums are lowercase.

---

## 1. SQLite schema (DDL)

Single database file per workspace: `<workspace>/.fieldnotes/fieldnotes.db`. Current shipped beta includes SQLite schema-version tracking and additive migrations during workspace open.

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE files (
  id            TEXT PRIMARY KEY,
  path          TEXT NOT NULL UNIQUE,        -- relative to workspace root
  kind          TEXT NOT NULL CHECK (kind IN ('pdf','pptx','docx','md','txt','csv')),
  display_name  TEXT NOT NULL,
  size_bytes    INTEGER NOT NULL,
  parse_status  TEXT NOT NULL CHECK (parse_status IN ('parsed','failed','skipped')),
  parse_summary TEXT,                        -- comprehension line, e.g. "5 trials, 200 rows"
  created_at    TEXT NOT NULL
);

CREATE TABLE chunks (
  id         TEXT PRIMARY KEY,
  file_id    TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  ordinal    INTEGER NOT NULL,               -- chunk order within file
  text       TEXT NOT NULL,
  anchor     TEXT NOT NULL,                  -- see §1.1 anchor format
  UNIQUE (file_id, ordinal)
);
CREATE INDEX idx_chunks_file ON chunks(file_id);

CREATE TABLE dataset_profiles (
  file_id     TEXT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
  profile_json TEXT NOT NULL                 -- serialized DatasetProfile, §4
);

CREATE TABLE concepts (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL UNIQUE,         -- normalized lowercase, e.g. "damping ratio"
  state        TEXT NOT NULL CHECK (state IN ('touched','shaky')),
  touch_count  INTEGER NOT NULL DEFAULT 1,
  miss_count   INTEGER NOT NULL DEFAULT 0,
  source_anchor TEXT,                        -- best supporting anchor, nullable
  updated_at   TEXT NOT NULL
);

CREATE TABLE quiz_attempts (
  id            TEXT PRIMARY KEY,
  concept_id    TEXT NOT NULL REFERENCES concepts(id),
  question      TEXT NOT NULL,
  options_json  TEXT NOT NULL,               -- JSON array of strings
  correct_index INTEGER NOT NULL,
  chosen_index  INTEGER,                     -- NULL until answered
  is_correct    INTEGER,                     -- 0/1, NULL until answered
  source_anchor TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX idx_quiz_concept ON quiz_attempts(concept_id);

CREATE TABLE artifacts (
  id          TEXT PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('chart','explainer','quiz_result','script')),
  title       TEXT NOT NULL,                 -- notebook card title
  payload_path TEXT,                         -- PNG or .py file under .fieldnotes/artifacts/
  payload_text TEXT,                         -- explainer prose / quiz score JSON
  answer_id   TEXT,                          -- groups artifacts from one answer
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_artifacts_answer ON artifacts(answer_id);

CREATE TABLE workspace_meta (
  key   TEXT PRIMARY KEY,                    -- 'course_title','brief_json','indexed_at'
  value TEXT NOT NULL
);
```

### 1.1 Anchor format (string, used everywhere a citation exists)

```
<file_id>#<locator>
  pdf:   f3a9…#p12/b4      (page 12, block 4)
  pptx:  81cd…#s8          (slide 8)
  docx:  22ab…#para41      (paragraph 41)
  csv:   9e0f…#schema      (profile-level reference)
```

Resolved by `GET /source/{file_id}/{locator}` (F6, F9).

---

## 2. SSE event contract

All events are `data: <json>\n\n` lines. Every payload carries `"event"` as its discriminator. TypeScript interfaces are normative for the frontend; Pydantic models mirror them 1:1 in the backend.

### 2.1 Channel: indexing — `GET /index/events/{run_id}`

```ts
type IndexEvent =
  | { event: "file_started";  file_id: string; display_name: string }
  | { event: "file_parsed";   file_id: string; display_name: string;
      parse_status: "parsed" | "failed" | "skipped";
      parse_summary: string }                       // comprehension line (F2, F3)
  | { event: "index_complete"; file_count: number; chunk_count: number }
  | { event: "brief_ready";   brief: WorkspaceBrief };   // §3.3
```

### 2.2 Channel: ask — `POST /ask` (SSE response)

```ts
type AskEvent =
  | { event: "intent";   answer_id: string; intent: Intent;
      targets: string[]; connect: boolean }          // Intent: §3.1
  | { event: "step";     answer_id: string;
      step: "retrieval" | "codegen" | "execution" | "grounding" | "retry";
      label: string;                                 // trace text, e.g. "wrote analysis.py"
      status: "started" | "ok" | "failed";
      duration_ms?: number;                          // present when status != "started"
      file_id?: string }                             // drives left-pane file highlight
  | { event: "token";    answer_id: string; text: string }   // answer prose stream
  | { event: "artifact"; answer_id: string; artifact_id: string;
      kind: "chart" | "script" | "explainer";
      title: string; url?: string }                  // url for chart PNGs
  | { event: "citations"; answer_id: string; chips: CitationChip[] }
  | { event: "concepts"; answer_id: string; updates: ConceptUpdate[] }
  | { event: "error";    answer_id: string; code: string; message: string;
      recoverable: boolean; request_id?: string }
  | { event: "done";     answer_id: string };

interface CitationChip {
  chip_type: "document" | "code";
  label: string;              // "ch6_damping.pdf §6.3" | "analysis.py output"
  anchor?: string;            // document chips (§1.1 format)
  artifact_id?: string;       // code chips
}

interface ConceptUpdate {
  concept_id: string;
  name: string;
  state: "touched" | "shaky";
}
```

Ordering guarantee per answer: `intent` → one or more `step` → interleaved `token`/`artifact` → `citations` → `concepts` → `done`. `error` may replace any tail and terminate stream cleanly.

### 2.3 Channel: quiz — `POST /quiz/start` (SSE response)

```ts
type QuizEvent =
  | { event: "question"; attempt_id: string; index: number; total: number;
      question: string; options: string[];
      source_label: string; source_anchor: string }
  | { event: "graded";   attempt_id: string; is_correct: boolean;
      correct_index: number; explanation: string;
      chip: CitationChip; concept_update: ConceptUpdate }
  | { event: "quiz_done"; score: number; total: number; artifact_id: string;
      refreshed_starters: StarterCard[] }            // loop closure (F7, F8)
  | { event: "error"; attempt_id?: string; code: string; message: string;
      recoverable: boolean; request_id?: string }
```

---

## 3. Responses API structured-output schemas

Passed as JSON Schema through the Responses API `text.format` mechanism. All use `"additionalProperties": false`.

### 3.1 Intent classification

```json
{
  "name": "route_intent",
  "schema": {
    "type": "object",
    "properties": {
      "intent":  { "type": "string",
                   "enum": ["retrieve", "analyze", "visualize", "connect", "quiz"] },
      "targets": { "type": "array", "items": { "type": "string" },
                   "description": "Relative file paths the question refers to; empty if none" },
      "connect": { "type": "boolean",
                   "description": "Whether to ground results in theory passages" }
    },
    "required": ["intent", "targets", "connect"],
    "additionalProperties": false
  }
}
```

### 3.2 Quiz question generation (one question per call)

```json
{
  "name": "quiz_question",
  "schema": {
    "type": "object",
    "properties": {
      "question":      { "type": "string" },
      "options":       { "type": "array", "items": { "type": "string" },
                         "minItems": 4, "maxItems": 4 },
      "correct_index": { "type": "integer", "minimum": 0, "maximum": 3 },
      "concept":       { "type": "string" },
      "source_anchor": { "type": "string",
                         "description": "Anchor of the chunk this question is drawn from" }
    },
    "required": ["question", "options", "correct_index", "concept", "source_anchor"],
    "additionalProperties": false
  }
}
```

Backend validates `source_anchor` against the chunks table before emitting; an unknown anchor rejects the question and re-prompts (prevents ungrounded questions).

### 3.3 Workspace brief

```json
{
  "name": "workspace_brief",
  "schema": {
    "type": "object",
    "properties": {
      "course_title": { "type": "string" },
      "summary":      { "type": "string",
                        "description": "2-3 sentences naming concrete findings" },
      "starter_cards": {
        "type": "array", "minItems": 3, "maxItems": 4,
        "items": {
          "type": "object",
          "properties": {
            "text":       { "type": "string" },
            "file_path":  { "type": "string",
                            "description": "The real file this card references" },
            "seed":       { "type": "string",
                            "enum": ["anomaly", "concept", "practice"] }
          },
          "required": ["text", "file_path", "seed"],
          "additionalProperties": false
        }
      }
    },
    "required": ["course_title", "summary", "starter_cards"],
    "additionalProperties": false
  }
}
```

```ts
interface WorkspaceBrief {          // mirrors 3.3; used in brief_ready + quiz_done
  course_title: string;
  summary: string;
  starter_cards: StarterCard[];
}
interface StarterCard { text: string; file_path: string; seed: "anomaly" | "concept" | "practice"; }
```

Backend validates every `file_path` against the files table; cards referencing unknown files are dropped (design.md §3.1: cards must name real files).

---

## 4. DatasetProfile (the data-minimization boundary)

This is the **only** representation of tabular data sent to the configured Responses model (dataflow.md). It is both the codegen prompt input and privacy boundary; raw dataset rows do not leave the machine.

```ts
interface DatasetProfile {
  file_path: string;               // relative, e.g. "labs/pendulum.csv"
  row_count: number;
  columns: ColumnProfile[];
  notes: string[];                 // profiler observations, e.g. "trial column has 5 distinct values"
}

interface ColumnProfile {
  name: string;
  dtype: "int" | "float" | "string" | "bool" | "datetime";
  null_count: number;
  // numeric columns only:
  min?: number; max?: number; mean?: number; std?: number;
  // string/categorical columns only:
  distinct_count?: number;
  top_values?: string[];           // at most 5
  // anomaly seeding (F3):
  outlier_flags?: OutlierFlag[];
}

interface OutlierFlag {
  group: string;                   // e.g. "trial=4"
  metric: string;                  // column the deviation was measured on
  z_score: number;                 // rounded to 1 decimal
}
```

Explicitly excluded from this shape: raw rows, cell values beyond `top_values` (max 5 short strings), and free-text columns' contents.

---

## 5. Pydantic / FastAPI request-response models

Derived directly from the above; listed for completeness. Codex should generate these as `backend/models.py` mirroring §2–§4 field-for-field.

| Endpoint | Request body | Response |
|---|---|---|
| `GET /health` | — | `{ status, version, mode, startup }` |
| `POST /index` | `{ "folder_path": str }` | `202` + `{ status, workspace_id, run_id, events }` |
| `GET /index/events/{run_id}` | — | SSE stream of `IndexEvent` |
| `POST /ask` | `{ "workspace_id": str, "question": str }` | SSE stream of `AskEvent` |
| `POST /quiz/start` | `{ "workspace_id": str, "concept_ids": [str] \| null }` (null = all shaky, then touched) | SSE stream of `QuizEvent` |
| `POST /quiz/answer` | `{ "workspace_id": str, "attempt_id": str, "chosen_index": int }` | SSE stream containing `graded` then `quiz_done` |
| `GET /notebook` | query: `workspace_id` | `{ "artifacts": ArtifactCard[] }` |
| `GET /artifact/{id}` | query: `workspace_id` | payload (PNG / script text / JSON) |
| `GET /source/{file_id}/{locator}` | query: `workspace_id` | `{ "text": str, "label": str, "file_path": str }` |

```ts
interface ArtifactCard {
  id: string;
  kind: "chart" | "explainer" | "quiz_result" | "script";
  title: string;
  created_at: string;             // ISO 8601
  url?: string;                   // charts only
}
```

---

## 6. Implementation notes

- Embeddings are stored in SQLite and reference persisted chunks; no external vector-store schema is required.
- Migrations and schema versioning are shipped as additive SQLite migrations during workspace open.
- Multiple local workspaces are registered by stable workspace ID. There are no user or collaboration tables.
