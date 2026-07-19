# Fieldnotes — Tech Stack

**Version:** 1.0
**Date:** July 17, 2026
**Companion to:** prd.md (resolves PRD §14 open question: local web server + browser, not Electron/Tauri)

---

## 1. Stack selection principles

1. **Optimize for Codex.** The majority of core functionality must be built in Codex sessions (submission requirement). Codex is strongest in mainstream, well-documented ecosystems — Python, FastAPI, React. No exotic frameworks.
2. **One runtime for agent + analysis.** The agent generates and executes Python analysis code, so the backend is Python — sandbox, parsers, and orchestration share one runtime with no cross-language bridge.
3. **Local-first by construction.** Files, index, embeddings, concept log, notebook, and code execution never leave the machine. Only retrieved passages, dataset schemas/summaries, and the user's question go to the GPT-5.6 API at question time.
4. **No schedule-killers.** No Docker isolation, no desktop packaging, no orchestration framework. Every layer is the simplest thing that satisfies the PRD.

---

## 2. Stack at a glance

| Layer | Choice | Why |
|---|---|---|
| App form factor | Local web server + browser | Zero packaging risk; demo video identical to a desktop app |
| Backend | Python 3.12 + FastAPI + Uvicorn | Async, SSE streaming, same runtime as generated analysis code |
| PDF parsing | PyMuPDF (fitz) | Fastest extraction; page/block anchors for citations (F2, F6, F9) |
| PPTX / DOCX parsing | python-pptx / python-docx | Battle-tested, Codex knows them cold |
| Tabular | pandas | Schema inference, summary stats, anomaly seeding (F2, F3) |
| Metadata / persistence | SQLite | Concept log, notebook, file metadata; restart survival (F9) with no DB server |
| Keyword search | rank_bm25 | Adequate alone for a 15-file corpus; zero-dependency fallback |
| Semantic search | Deterministic local embeddings in SQLite | Current shipped beta keeps semantic pipeline local without external vector store dependency |
| Agent layer | OpenAI Python SDK directly (no framework) | 5-intent router + linear pipeline needs no graph orchestration |
| Model | GPT-5.6 (hackathon requirement) | Runtime router, code generation, grounding, quiz generation |
| Sandbox | subprocess + resource limits in a dedicated venv | PRD §8.2; no containers |
| Charts | matplotlib (Agg backend) → PNG | Backend renders; frontend needs no charting library |
| Frontend | React + Vite + Tailwind CSS | Single-page three-pane grid; fast scaffold |
| Streaming | Server-Sent Events over fetch streams | One-directional router trace + indexing progress; simpler than WebSockets and matches shipped frontend |
| Build tool | Codex with GPT-5.6 | Submission requirement; capture /feedback session ID |

---

## 3. Backend

### 3.1 Framework

- **Python 3.12, FastAPI, Uvicorn.**
- Endpoints:
  - `POST /index` — kick off folder indexing; progress streamed via SSE.
  - `GET /index/events/{run_id}` — SSE stream of per-file indexing progress and comprehension lines (F2, F3).
  - `POST /ask` — SSE stream: router trace events, answer tokens, artifact references (F4, F5, F6, F9).
  - `POST /quiz`, `POST /quiz/answer` — quiz generation and answer grading from the concept log (F7, F8).
  - `GET /notebook`, `GET /artifact/{id}` — notebook listing and artifact retrieval scoped by `workspace_id` (F9).
  - `GET /source/{file_id}/{anchor}` — resolve a citation chip to its passage scoped by `workspace_id` (F6, F9).

### 3.2 Parsing layer

- **PyMuPDF** for PDFs — extract text with page and block anchors.
- **python-pptx** for lecture decks; slide number = anchor.
- **python-docx** for reports; paragraph index = anchor.
- **pandas** for CSVs — columns, dtypes, row counts, basic distributions, simple outlier detection (z-score per numeric column) to seed starter cards (F3).

### 3.3 Index

- **SQLite** — file metadata, anchors, concept log, notebook artifacts, quiz history.
- **BM25 (rank_bm25)** over chunked text — keyword recall.
- Deterministic local embeddings persisted in SQLite.
- Hybrid retrieval merges BM25 scores with locally computed vector similarity, deduped by anchor.
- No external vector-store dependency in current shipped beta.

### 3.4 Agent layer

- **OpenAI Python SDK directly. No LangGraph / LangChain.** Current beta uses planner/executor modules around a linear execute-and-ground pipeline:
  1. Classify intent with GPT-5.6 structured outputs: `retrieve | analyze | visualize | connect | quiz` (combinations allowed).
  2. Build typed execution plan.
  3. Execute local retrieval and analysis steps sequentially.
  4. Use Responses API flat tools where needed for grounded retrieval.
  5. Stream every step as SSE trace events.
- **Verify GPT-5.6 structured-output and tool-calling specifics against the current docs** (linked from the hackathon page) before locking prompt formats — do not assume parity with older API versions.
- Analysis codegen is schema-aware: the prompt includes the dataset's columns, dtypes, and summary stats, never the raw file.
- One automatic retry on sandbox failure with the error message fed back to the model (PRD §13 risk mitigation).

### 3.5 Sandbox

- `subprocess.run` in a **dedicated venv** preloaded with pandas, numpy, scipy, matplotlib.
- Limits: `timeout=15`, memory cap via `resource.setrlimit`, cwd scoped to the workspace directory, network access blocked.
- matplotlib on the **Agg** backend; charts written as PNGs, served to the frontend as static files or base64.
- Generated scripts are retained per-answer and inspectable via the code citation chip (F9, F6).
- **Explicitly out of scope:** Docker/container isolation. Threat model is the student's own machine and data; containers are the classic hackathon schedule-killer.

---

## 4. Frontend

- **React + Vite + Tailwind CSS.** Single page, CSS grid for the three-pane layout (files + concept log / investigation thread / notebook).
- A fetch-stream SSE reader consumes indexing, ask, and quiz streams.
- Charts arrive as images from the backend — no charting library.
- Quiz state swaps the center pane only; sidebar and notebook stay mounted.
- Folder selection: native path input (backend is local, so a pasted path works for v1); File System Access API as a Chrome-only enhancement if time permits.
- Header lock badge ("local workspace") always visible.

---

## 5. Model usage (GPT-5.6)

| Runtime task | Mechanism |
|---|---|
| Intent classification | Structured outputs (small enum schema) |
| Workspace brief + starter cards | Single call with index inventory + dataset summaries |
| Analysis code generation | Function-calling loop with schema-aware prompt |
| Answer grounding / connect | Retrieved passages + computed results in context |
| Quiz generation & grading | Concept log + cited source chunks; one question per call |

**Data minimization:** requests carry retrieved passages, schemas, and summaries — never the folder, never full raw datasets where avoidable.

---

## 6. Repository layout (day-1 Codex scaffold)

```
fieldnotes/
├── run.sh                  # starts backend + frontend with one command
├── README.md               # setup, Codex/GPT-5.6 usage narrative, sample data guide
├── demo_course/            # bundled Physics II folder (~15 files, incl. pendulum.csv)
├── backend/
│   ├── main.py             # FastAPI app + SSE endpoints
│   ├── indexer/            # parsers, chunking, BM25 + embeddings, SQLite models
│   ├── agent/              # router, tools, prompts, trace events
│   ├── sandbox/            # venv runner, limits, chart capture
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── panes/          # FilesPane, ThreadPane, NotebookPane
    │   ├── components/     # RouterTrace, CitationChips, StarterCards, QuizView
    │   └── lib/            # api.ts SSE fetch client
    └── package.json
```

---

## 7. Hackathon compliance notes

- Scaffold the repo in a **Codex session** and keep core functionality inside Codex sessions — this anchors the required `/feedback` session ID.
- README must document where Codex accelerated the workflow, key decisions, and how GPT-5.6 powers the runtime (router + codegen) — judged under Technological Implementation.
- Repo public with a license, or private and shared with testing@devpost.com and build-week-event@openai.com.
- Bundle `demo_course/` so judges can run the project without hunting for data.

---

## 8. Decision log

| Decision | Chosen | Rejected | Rationale |
|---|---|---|---|
| Form factor | Local web server + browser | Electron / Tauri | Packaging adds ~1 day of risk for zero judging value |
| Backend language | Python | Node/TypeScript | Agent generates Python; one runtime, no bridge |
| Agent orchestration | Plain SDK loop | LangGraph / LangChain | 5 intents + linear pipeline; less code, easier 2 AM debugging, clearer README |
| Embeddings | Deterministic local vectors | OpenAI embeddings API | Keeps indexing fully local in shipped beta |
| Search fallback | BM25 only | — | Honest fallback if embeddings eat schedule; fine for 15 files |
| Isolation | subprocess + rlimits | Docker | Matches threat model; avoids the classic schedule-killer |
| Real-time channel | SSE | WebSockets | One-directional streams only; EventSource is simpler |
| Charts | Backend matplotlib PNGs | Frontend charting lib | One less dependency; charts are artifacts anyway (F9) |
