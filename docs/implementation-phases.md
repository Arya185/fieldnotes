# Fieldnotes — Implementation Phases

**Version:** 1.0
**Date:** July 17, 2026
**Companions:** prd.md, techstack.md, dataflow.md, design.md, schemas.md
**Hard deadline:** Tuesday, July 21, 2026, 5:00 PM PT

---

## 0. How to read this document

Seven phases, strictly ordered by dependency. Each phase has **deliverables**, an **exit test** (a concrete thing that must work before moving on — never advance on "mostly working"), and a **cut line** (what to drop if the phase overruns). Phases 1–5 are the build; Phase 6 is submission and is immovable.

Every phase runs inside Codex sessions with GPT-5.6. Phase 1's session is the anchor for the required `/feedback` session ID, so the majority of core functionality (Phases 1–4) should stay within Codex.

**Demo-driven rule:** every deliverable must appear in the 3-minute demo (prd.md §11, Demo script) or directly enable something that does. Anything else is out of scope by default.

---

## Phase 0 — Setup and unblocking (Jul 17, morning) ✅ time-critical

| Item | Detail |
|---|---|
| Codex credits | Request on the Devpost Resources tab — **deadline 12:00 PM PT today** |
| Accounts | OpenAI account, repo created (public with license, or private + shared with testing@devpost.com and build-week-event@openai.com) |
| API verification | One throwaway script: confirm GPT-5.6 structured-outputs and function-calling parameter names against current docs (techstack.md §3.4 caveat) |
| Docs in repo | Commit all six companion docs — prd.md, techstack.md, dataflow.md, design.md, schemas.md, and this file — to `/docs` so every Codex session can reference them. Also commit `architecture.md` as a 7th, non-binding/descriptive doc (see its own authority note — it defers to schemas.md/techstack.md/dataflow.md on any conflict and is not part of rule.md's authority hierarchy) |

**Exit test:** a `curl`/script call to GPT-5.6 returns a valid structured output against the intent schema (schemas.md §3.1).
**Cut line:** none — this phase cannot be cut or shortened.

---

## Phase 1 — Scaffold + ingest + index (Jul 17, rest of day)

**Codex session goal:** generate the repo per techstack.md §6, then build the local pipeline.

Deliverables:
1. Monorepo scaffold: `backend/` (FastAPI + Uvicorn), `frontend/` (Vite + React + Tailwind), `run.sh`, `demo_course/` stub.
2. `backend/models.py` generated field-for-field from schemas.md §2–§5.
3. SQLite bootstrap from schemas.md §1 DDL; `.fieldnotes/` workspace directory convention.
4. Parsers: PyMuPDF (PDF, page/block anchors), python-pptx (slide anchors), python-docx (paragraph anchors), pandas CSV profiler emitting `DatasetProfile` with z-score outlier flags (schemas.md §4).
5. Chunking + BM25 index; fastembed + ChromaDB vector index.
6. `POST /index` + `GET /index/events` SSE stream emitting `file_started` / `file_parsed` / `index_complete` per the contract.
7. First cut of `demo_course/`: ~10 files including `pendulum.csv` with a deliberately overdamped Trial 4.

**Exit test:** indexing `demo_course/` streams per-file events, populates SQLite (files, chunks, dataset_profiles), and the pendulum profile carries an `outlier_flags` entry for `trial=4`.
**Cut line:** drop fastembed/ChromaDB → BM25 only (pre-approved fallback, techstack.md §3.3). Never cut anchors or the CSV profiler — citations and the demo depend on them.

---

## Phase 2 — Agent core: router + analyze path (Jul 18)

**The make-or-break phase.** The Trial 4 investigation (demo wow moment 2) must work end-to-end by tonight.

Deliverables:
1. Intent classification via structured outputs (schemas.md §3.1), with fallback-to-`retrieve` on invalid output.
2. Tool loop (plain SDK, no framework): `search_index`, `run_analysis`, `render_chart`.
3. Sandbox: dedicated venv (pandas/numpy/scipy/matplotlib), `subprocess.run` with `timeout=15`, `resource.setrlimit` memory cap, cwd scoped to workspace, no network; Agg-backend PNGs captured as artifacts.
4. Schema-aware codegen prompt (DatasetProfile in, script out); one automatic retry feeding the error back.
5. `POST /ask` SSE stream emitting the full `AskEvent` sequence: `intent` → `step`s → `token`s / `artifact` → `citations` → `concepts` → `done`.
6. Grounding call combining computed results with retrieved passages (`connect` behavior).
7. Artifact persistence: script + PNG written under `.fieldnotes/artifacts/`, rows in the artifacts table.

**Exit test:** `curl -N POST /ask` with "Why does Trial 4 look different?" streams a correct event sequence ending in a chart artifact, a document chip anchored to the damping chapter, and a code chip — with no frontend involved.
**Cut line:** drop `connect` as a distinct intent (fold into analyze's grounding call — prd.md §14 already anticipated this). Drop `visualize` as separate from `analyze`. Never cut the trace events or the retry.

---

## Phase 3 — Workspace UI (Jul 19, first half)

**Codex session goal:** the three-pane workspace per design.md, consuming the streams built in Phases 1–2.

Deliverables:
1. Three-pane CSS grid + header with lock badge (design.md §2).
2. `useEventSource` hook; indexing state with per-file tick-off and comprehension lines.
3. Investigation thread: user bubbles, **RouterTrace** strip rendered from `step` events, streamed answer prose, inline chart images, **CitationChips** with drawer (passage view via `GET /source/...`; script + output view via `GET /artifact/...`).
4. Left pane: file list with type icons and `file_id`-driven active highlight; ConceptChips (neutral/amber).
5. Right pane: NotebookCard list from `GET /notebook`; empty state copy.
6. Input row with persistent "Quiz me" button (wired in Phase 4).

**Exit test:** the full Trial 4 flow runs in the browser — question typed, trace assembles live, chart renders, both chips open their drawers, artifact appears in the notebook.
**Cut line:** drop the drawer for document chips → open passage text in a simple modal or alert-style panel. Drop file-highlight sync. Never cut the RouterTrace strip — it is the demo's proof of the agentic layer.

---

## Phase 4 — Brief, starters, quiz loop (Jul 19 second half – Jul 20 morning)

Deliverables:
1. Workspace brief generation (schemas.md §3.3) with file-path validation; brief card UI with metric-card inventory row and StarterCards (tap = send question).
2. Concept log writes: concepts upserted per answer (`concepts` events), amber transition on repeated asks.
3. Quiz path: `POST /quiz` + `POST /quiz/answer` per the QuizEvent contract; source_anchor validation with re-prompt; quiz state takes over the center pane only, one question at a time with source citation.
4. Loop closure: grades update concept state (miss → shaky/amber, live chip transition), `quiz_done` returns `refreshed_starters`, brief card refreshes.
5. Quiz result saved as a notebook artifact.

**Exit test:** demo wow moment 3 works: miss a quiz question → concept chip flips amber in the left pane → starter cards visibly refresh.
**Cut line:** drop adaptive question selection → questions from shaky-then-touched concepts in order. Drop the graded explanation chip → plain text explanation. Never cut the amber transition or starter refresh — the loop closure is the Education-track argument made visible.

---

## Phase 5 — Hardening, demo data, README (Jul 20)

Deliverables:
1. Final `demo_course/` (~15 files): coherent Physics II set — 4 textbook-chapter PDFs, 6 lecture decks, lab report draft, 3 CSVs. Trial 4 anomaly tuned so the chart is visually unmistakable in compressed 1080p (design.md §8).
2. Error states per design.md §6 voice ("Analysis failed on first attempt — retrying with the error in context"); `error` event rendering.
3. Full demo dry run ×3 from a clean `.fieldnotes/` delete; fix every stumble.
4. README: setup, `run.sh` usage, sample-data guide, **where Codex accelerated the workflow, key decisions (import decision log from techstack.md §8), how GPT-5.6 powers the runtime** — judged material.
5. Repo hygiene: license, `.gitignore` for `.fieldnotes/`, no keys committed.

**Exit test:** a colleague (or a clean machine) clones the repo, runs `run.sh`, and completes the demo flow using only the README.
**Cut line:** reduce demo_course to 10 files; drop non-demo error states. Never cut the README Codex/GPT-5.6 narrative.

---

## Phase 6 — Submission (Jul 21, immovable)

| Time (PT) | Item |
|---|---|
| Morning | Record demo video: <3 min, the prd.md §11 arc, audio explicitly covering how Codex and GPT-5.6 were used; upload public to YouTube |
| Midday | Capture the `/feedback` Codex session ID from the session where core functionality was built |
| By 3:00 PM | Devpost submission draft: category (Education), project description, video URL, repo URL, session ID — submit early, edit later if needed |
| 5:00 PM | Hard deadline. Do not be uploading a video at 4:55 |

**Exit test:** submission confirmed on Devpost with all required fields.

---

## Dependency graph

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 5 ──► Phase 6
                │                        ▲
                └──────► Phase 4 ────────┘   (brief/quiz need index + agent;
                                              quiz UI needs Phase 3 panes)
```

Phase 4's backend work (brief generation, quiz endpoints) can start in parallel with Phase 3's UI if ahead of schedule — the schemas.md contracts make the panes and endpoints independently buildable.

---

## Global cut order (if the schedule collapses)

In order, cut: (1) vector embeddings → BM25, (2) `connect`/`visualize` as distinct intents, (3) citation drawers → simple panels, (4) file-highlight sync, (5) quiz question adaptivity, (6) demo_course size. **Never cut:** router trace, sandbox execution with retained scripts, anchored citations, the amber-concept/starter-refresh loop, the workspace brief. Those five are the product.

---

## Codex session plan (submission requirement)

| Session | Phase(s) | Anchor prompt |
|---|---|---|
| S1 | 1 | "Scaffold per docs/techstack.md §6; generate backend/models.py field-for-field from docs/schemas.md; build the index pipeline to the Phase 1 exit test" |
| S2 | 2 | "Build the agent loop and sandbox per docs/techstack.md §3.4–3.5 against the AskEvent contract; exit test is the curl trace" |
| S3 | 3 | "Build the three-pane UI per docs/design.md consuming the SSE contracts" |
| S4 | 4 | "Brief, starters, quiz loop per schemas.md §2.3/§3.2/§3.3" |
| S5 | 5 | "Hardening + README" |

Use `/feedback` in the session carrying the most core functionality (expected: S2) for the submission ID; note all session IDs as you go rather than reconstructing later.
