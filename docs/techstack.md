# Fieldnotes Tech Stack

**Version:** `1.0.0-beta.1`
**Status:** shipped beta architecture

## Stack

| Layer | Shipped choice |
|---|---|
| Form factor | Local FastAPI service served in a browser |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Frontend | React, TypeScript, Vite, handwritten CSS |
| Persistence | Per-workspace SQLite database with additive schema migrations |
| Parsing | PyMuPDF, python-pptx, python-docx, pandas, text/CSV parsers |
| Retrieval | BM25, deterministic local embeddings, SQLite vector search, configurable hybrid fusion, deterministic reranking |
| LLM | OpenAI Python SDK and the Responses API; default model `gpt-5` |
| Offline mode | Deterministic fake client, enabled with `FIELDNOTES_USE_FAKE_LLM=1` |
| Analysis | Local Python subprocess sandbox with pandas, NumPy, SciPy, and matplotlib Agg |
| Streaming | Fetch-consumed Server-Sent Events |
| Observability | Optional internal tracing, metrics, retrieval inspection, and benchmark JSON |

## Runtime boundaries

Files, chunks, embeddings, workspace registry, quiz attempts, concepts, notebook records, and artifact files stay local. In live mode, the Responses API receives only the question, retrieved passages, permitted dataset profiles, and local analysis results needed to ground an answer. Fake mode makes no OpenAI request.

The backend uses `client.responses.create()` for live calls. Structured output is supplied through `text.format`; tool definitions use the flat Responses API shape, and tool results are returned as `function_call_output` items. No Chat Completions API convention is used.

## Retrieval and indexing

`POST /index` creates a stable workspace record, starts a run-scoped event stream, discovers supported files, parses them, chunks text, profiles CSV data, persists the run transactionally, and creates deterministic local embeddings. Parsing supports PDF, PPTX, DOCX, Markdown, text, and CSV. Failed or unsupported files are represented by parse status rather than crashing the run.

Retrieval remains configurable with `FIELDNOTES_RETRIEVAL_PROVIDER= bm25 | vector | hybrid`. Hybrid normalizes BM25 and cosine score ranges before weighted fusion. The default is `hybrid`; reranking and context budgeting run before live grounding.

## Frontend

The React single-page interface is desktop-first and uses local component state plus browser storage for client-only preferences. `frontend/src/App.tsx` composes the shell, while `components/Composer.tsx`, `components/EmptyState.tsx`, `components/WorkspaceOverview.tsx`, and `components/LockBadge.tsx` cover shared UI. `frontend/src/lib/api.ts` owns REST and fetch-SSE calls. Vite proxies local API routes to `127.0.0.1:8000` during development.

## Configuration

The backend loads project-root `.env` before startup validation without overriding shell variables. Required live configuration is `OPENAI_API_KEY`; `OPENAI_MODEL` defaults to `gpt-5`. See [configuration.md](configuration.md) for retrieval, embedding, context, and telemetry settings.

## Commands

```bash
python -m unittest discover -s tests
python scripts/exit_phase0.py
python scripts/exit_phase1.py
python scripts/run_benchmarks.py
python scripts/release_check.py
cd frontend && npm test && npm run build
```

`run.sh` is a Unix convenience launcher only. Use direct Python and npm commands on Windows.
