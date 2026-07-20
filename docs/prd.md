# Fieldnotes — Product Requirements Document

**Version:** 1.0.0-beta.1 · **Status:** Implemented beta product contract

---

## 1. Overview

Fieldnotes is a local-first AI learning workspace that turns a student's existing course folder — textbooks, lecture notes, slides, assignments, lab reports, and experiment datasets — into an active environment for understanding, investigating, connecting, and practicing.

Unlike "chat with PDF" tools, Fieldnotes runs an agentic reasoning layer that decides *how* to answer: retrieving passages, writing and executing analysis code against the student's own data, generating visualizations, or building practice quizzes from what the student struggled with in the session. Files, indexes, and learning history never leave the machine; only minimal, task-scoped context is sent to the model for reasoning.

**One-liner:** Fieldnotes turns a folder into an interactive learning environment.

---

## 2. Problem statement

Students already possess large collections of learning material, but these resources are passive and fragmented. Students lose time searching across files, switching contexts, and manually connecting theory (a textbook chapter) with practice (their own experiment data). Existing AI study tools provide conversational retrieval over uploaded documents but cannot *work with* a student's data — they can quote the lab manual, but they cannot open the CSV, compute the residuals, and show why Trial 4 is an outlier.

The core gap: students have access to information, but lack an intelligent layer that can actively work across their own learning materials and data.

### Proof-of-difference scenario

Given the same question — "Why does Trial 4 look different?" — a chat-with-PDF tool paraphrases the lab manual. Fieldnotes loads `pendulum.csv`, writes and executes analysis code locally, plots the anomalous decay curve, and cross-references the textbook section on damping. This contrast is the product's core demonstration and must be reproducible in the demo.

---

## 3. Target user

**Primary persona:** STEM undergraduates in lab-based courses (physics, chemistry, biology, engineering) who generate experimental data weekly and must connect it to theory for lab reports and exams.

**Why this persona:** They have exactly the folder Fieldnotes needs (readings + datasets + reports), a recurring weekly pain (lab analysis and write-ups), and a pedagogical stake — lab courses exist to train the investigate–analyze–connect loop of real research practice. Fieldnotes doesn't just help them pass; it teaches them to work the way researchers work.

**Bridge persona (expansion, not v1 target):** Graduate students and lab researchers. The same architecture serves them by reweighting the agent router (more analyze/connect, less quiz) and swapping the concept log for an open-questions log. This is the "what's next" narrative, not a second demo audience.

**Explicit non-audiences for v1:** K-12 students, humanities-only course loads, instructors/LMS administrators.

---

## 4. Goals and non-goals

### Goals

1. Demonstrate a working agentic router that visibly chooses between retrieval, code-executing data analysis, and quiz generation.
2. Deliver a complete, coherent product experience (three-pane workspace, onboarding brief, persistent notebook) — not a technical proof of concept.
3. Keep all source files, indexes, and learning history on the student's machine; send only task-scoped context to the configured Responses API model in live mode.
4. Close the learning loop honestly: practice quizzes are generated from a session-level concept log, and quiz results refresh the suggested starting points.
5. Satisfy every OpenAI Build Week submission requirement (Section 10).

### Non-goals (v1)

- No persistent cross-session learner model or spaced-repetition scheduling. "Adaptive" practice means: generated from concepts the student asked about or answered incorrectly *in this session*.
- No multi-course workspaces, collaboration, sharing, or cloud sync.
- No file editing or authoring — Fieldnotes reads course materials; it does not write the lab report.
- No LMS integration.
- No mobile client. Desktop web app only.

---

## 5. User flow

The end-to-end flow is: point at course folder → index with visible progress → workspace brief with suggested starting points → student asks (or taps a suggestion) → visible agent router selects an action → grounded answer with citations, artifacts saved to notebook → concept log accumulates → practice quiz built from the session → quiz results refresh the suggested starting points (loop).

### 5.1 Onboarding: folder → brief

The student selects a local folder. Indexing shows per-file progress with a live log line each (e.g., "parsed pendulum.csv — 5 trials, 200 rows"), making the 20–30 second wait read as comprehension rather than loading. Indexing ends in a **workspace brief**, not an empty chat box:

- A one-paragraph characterization of the course inferred from contents ("This looks like a lab course on oscillations…").
- File-type counts (chapters, decks, datasets) that double as an index audit.
- Three to four tappable **suggested starting points** derived from the actual content, at least one of which references a real detected anomaly or dataset feature.

This solves the cold-start problem: the burden of knowing what to ask never falls on the student.

### 5.2 Investigation loop

The student asks a question or taps a suggestion. The **agent router** classifies intent into one of {retrieve, analyze, visualize, connect, quiz} and displays a compact live trace of its steps (see 6.3). For analyze/visualize intents, the agent generates Python against the indexed dataset schema, executes it in a local sandbox, and grounds its explanation in both the computed result and cited source passages. Every answer ends with clickable citation chips; every generated artifact (chart, explainer, quiz result) is saved to the notebook panel.

### 5.3 Practice loop

Throughout the session, a **concept log** records concepts touched and concepts that appear shaky (asked about repeatedly, or missed in a quiz). The persistent "Quiz me" affordance generates questions *from the log*, each citing the source file it was drawn from. Quiz results mark concepts resolved or still shaky, and refresh the suggested starting points — closing the Learn → Investigate → Understand → Practice cycle with real data, no fake learner model.

---

## 6. Product surface and UX requirements

### 6.1 Layout

A single-page desktop web app with three panes inside a workspace header:

| Region | Contents |
|---|---|
| Header | Course name, "local workspace" lock badge (always visible), settings |
| Left sidebar (~180px) | File tree with type icons; active file highlighted; concept log chips below (amber = shaky, neutral = touched) |
| Center pane (flexible) | Investigation thread: user messages, router trace strip, grounded answers with inline charts and citation chips; input box with permanent "Quiz me" button |
| Right panel (~220px) | Notebook: reverse-chronological cards for every saved artifact (charts, explainers, quiz scores) with timestamps |

### 6.2 Onboarding brief (screen 1)

A centered card (not a chat message) containing the course characterization paragraph, the counts row, and the suggested-starting-point buttons. Requirement: each suggestion must name a real file or real detected feature from the index.

### 6.3 Router trace (the hero element)

A thin monospace strip rendered above each answer, streaming the agent's step events in real time. Examples:

- `agent · analyze ✓ read pendulum.csv → wrote analysis.py → ran locally · 1.8s ✓ matched ch6_damping.pdf §6.3`
- `agent · retrieve ✓ 3 passages from ch5_shm.pdf`
- `agent · quiz ✓ 6 questions from concept log`

This is the primary visual differentiator from chat-with-PDF and the key evidence for the Technological Implementation judging criterion. It must appear for every answer.

### 6.4 Grounded answers

Every answer ends with citation chips: source-document chips (file + section) and, for computational answers, a code chip. Clicking the code chip opens the actual generated script and its stdout in a drawer — judges must be able to verify the code is real.

### 6.5 Notebook

Every generated chart, explanation, and quiz score is appended as a card with title, type icon, and timestamp. Clicking a card reopens the artifact. Implementation may be a simple persisted list; the product value is cumulative work, not notebook features.

### 6.6 Quiz view

Takes over the center pane only (sidebar and notebook remain). One question at a time; each question cites the source file it was generated from. On completion: score, per-concept breakdown, and updated concept-log chips.

### 6.7 States and copy

- Empty/first-run: single "Choose a course folder" action with a one-line privacy statement.
- Indexing: per-file progress with live log lines (6.1 onboarding behavior).
- Errors: plain-language, actionable ("Couldn't parse lecture03.pptx — skipped it. 13 of 14 files indexed.").
- All UI copy in sentence case; no exclamation marks; privacy claim worded precisely ("Files never leave this machine. Only the context needed for each answer is sent for reasoning.").

---

## 7. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| F1 | Ingest a user-selected local folder containing PDF, PPTX, DOCX, MD/TXT, and CSV files | P0 |
| F2 | Build a local index: extracted text chunks with source anchors (file, page/section), plus dataset schemas (columns, types, row counts, basic stats) for every CSV | P0 |
| F3 | Generate the workspace brief and 3–4 content-derived suggested starting points on index completion | P0 |
| F4 | Route each user query to an intent in {retrieve, analyze, visualize, connect, quiz} via the configured Responses API model in live mode, and stream router step events to the UI trace | P0 |
| F5 | For analyze/visualize: generate Python against the indexed schema, execute in a local sandboxed process, capture stdout/figures, and ground the answer in the results | P0 |
| F6 | For retrieve/connect: answer from indexed chunks with mandatory citation chips (file + section) | P0 |
| F7 | Maintain a session concept log; mark concepts shaky on repeat questions or incorrect quiz answers | P0 |
| F8 | Generate quizzes from the concept log; each question cites its source file; results update the log and refresh suggestions | P0 |
| F9 | Persist all artifacts to the notebook panel; clicking reopens the artifact; code chips open the generated script + output | P0 |
| F10 | "Local workspace" badge and precise privacy copy always visible | P1 |
| F11 | Graceful handling of unparseable files (skip, report, continue) | P1 |
| F12 | Reset/re-index a workspace | P2 |

---

## 8. Technical architecture

### 8.1 Components

- **Desktop web app:** Fieldnotes is served locally in the browser as a three-pane desktop web application.
- **Indexer:** local pipeline extracting text (per-page/section anchors) and CSV schemas into a persistent local store. No cloud storage.
- **Agent runtime:** orchestrates router → retrieval/document access/schema access/local analysis → grounded answer. The configured OpenAI Responses API model performs live intent classification, code generation, explanation, quiz generation, and concept-log updates; deterministic fake mode is available for offline use.
- **Local code sandbox:** generated Python executes in a subprocess with a restricted working directory (the workspace), captured stdout/stderr, and chart artifact export. No network access from the sandbox.
- **Event stream:** agent step events stream to the UI as live updates to drive the router trace.

### 8.2 Local-first boundary (precise claim)

Stored locally, always: source files, index, embeddings, concept log, notebook artifacts, generated code. Sent to the model per request: the user's question, the minimal retrieved chunks or schema needed for the task, and (for grounding) computed results. Never sent: whole files, the full index, or learning history in bulk.

### 8.3 Build-tooling requirement (hackathon)

The product uses Codex during development and the OpenAI Responses API for live runtime reasoning. The default configured runtime model is `gpt-5`; fake mode is deterministic and never calls OpenAI.

---

## 9. Scope and milestones (July 17–21)

| Day | Milestone |
|---|---|
| Jul 17 (Fri) | Request Codex credits (12:00 PM PT deadline). Scaffold app in Codex; indexer for PDF + CSV; sample Physics II workspace assembled |
| Jul 18 (Sat) | Agent routing + local analysis sandbox + grounded retrieval with citations; live router trace in the UI |
| Jul 19 (Sun) | Three-pane UI complete: onboarding brief, suggestions, notebook, concept log; quiz generation + quiz view |
| Jul 20 (Mon) | Polish: error states, indexing progress log, code-chip drawer; end-to-end rehearsal of the demo script; README with Codex usage narrative |
| Jul 21 (Tue) | Record <3-minute demo video; capture /feedback session ID; final repo check; submit before 5:00 PM PT |

**Cut list (pre-agreed, cut in this order if behind):** F12 reset, DOCX/PPTX parsing (ship PDF + CSV + MD only), connect intent (fold into retrieve), quiz per-concept breakdown (ship score only).

---

## 10. Hackathon submission compliance checklist

Release-submission details are operational work, not runtime requirements. They are tracked in `tracker.md` and the release documentation.

### Judging-criteria mapping

- **Technological implementation:** visible router trace, real generated-and-executed code behind every analysis answer, code chips proving it.
- **Design:** complete three-pane workspace with onboarding, states, and persistent notebook — a product, not a demo script.
- **Potential impact:** narrow, credible persona (lab-course STEM undergrads) with a weekly recurring pain, demonstrated end-to-end on real course data.
- **Quality of idea:** beyond-RAG agentic layer + honest local-first architecture + closed learning loop; researcher-bridge framing shows understanding of the problem space.

---

## 11. Demo script (3 minutes)

1. (0:00–0:30) Pick the Physics II folder; indexing log ticks; workspace brief appears with counts and suggestions — *wow moment 1: it understood the folder before I asked anything.*
2. (0:30–1:30) Tap "Trial 4 deviates — investigate?"; router trace streams (read CSV → wrote code → ran locally → matched ch6); decay chart renders; click the code chip to show the real script — *wow moment 2: it worked with my data, not just my documents.*
3. (1:30–2:20) Ask "Explain this using my textbook"; retrieve trace + citation chips; concept log chip turns amber; hit "Quiz me"; answer two questions, one sourced from the CSV analysis — *wow moment 3: the loop closes.*
4. (2:20–3:00) Notebook recap (chart, explainer, quiz score all persisted); close with the local-first boundary and live-versus-fake-mode behavior.

---

## 12. Success metrics

- **Hackathon:** submission accepted with all requirements met; demo reproduces all three wow moments without edits; judges can run the project from the README in under 10 minutes using the bundled sample folder.
- **Product (post-hackathon):** time-to-first-insight under 60 seconds from folder selection; ≥1 executed-code analysis per session; ≥50% of sessions end with a quiz taken.

---

## 13. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Code-generation path is flaky on arbitrary CSVs | Constrain the demo to the bundled sample workspace; use schema-grounded prompts and surface sandbox failures honestly |
| PDF parsing quality varies | Prefer clean, text-native PDFs in the sample folder; F11 graceful skip for failures |
| "Local-first" challenged because reasoning is cloud-based | Precise boundary language (8.2) in UI, README, and video; never claim offline operation |
| Scope creep vs. 4-day window | Pre-agreed cut list (Section 9); suggestions and notebook are lists, not systems |
| Router misclassifies intent | Fallback to retrieve; the trace makes misroutes visible and debuggable during rehearsal |
| /feedback session ID forgotten until the end | Capture the session ID on day 1 and log it in the repo |

---

## 14. Open questions

1. Local server + browser delivery selected for v1: fastest path to a judge-runnable desktop web app with the fewest packaging risks.
3. Does the quiz view need free-text answers (LLM-graded) or multiple-choice only for v1? Default: multiple-choice only.
