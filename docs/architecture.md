# Fieldnotes — Architecture Overview

**Version:** 1.0.0-beta.1  
**Date:** July 18, 2026  
**Purpose:** Describe shipped beta runtime. This document explains system architecture only. It does **not** define APIs, data contracts, or event schemas.

**Companions:** prd.md, techstack.md, dataflow.md, schemas.md, design.md

> **Authority:** This document is descriptive only. If any statement conflicts with `schemas.md`, `techstack.md`, or `dataflow.md`, those documents take precedence.

---

# 1. Overview

Fieldnotes is a **local-first AI learning workspace**.

The system is organized into four major layers:

1. User Interface
2. Application Backend
3. Local Storage & Retrieval
4. GPT-5.6 Reasoning

Each layer has a single responsibility.

The architecture intentionally minimizes cloud dependency:

- source files remain local
- indexes remain local
- notebook remains local
- generated artifacts remain local

GPT-5 is used through Responses API for reasoning tasks. Internal release smoke can swap deterministic fake client without changing public API surface.

---

# 2. High-level architecture

```
┌────────────────────────────────────────────┐
│               React Frontend               │
│                                            │
│  Workspace • Chat • Quiz • Notebook        │
└──────────────────────┬─────────────────────┘
                       │
                  REST + SSE
                       │
┌──────────────────────▼─────────────────────┐
│             FastAPI Backend                │
│                                            │
│  Routing                                   │
│  Retrieval orchestration                   │
│  Analysis orchestration                    │
│  Notebook persistence                      │
└───────┬──────────────┬───────────────┬─────┘
        │              │               │
        ▼              ▼               ▼
 Local Storage   Local Retrieval   Python Sandbox
(SQLite)         (BM25 + Vector)   (Analysis)

        │
        ▼

     GPT-5.6
 (Reasoning only)
```

---

# 3. Layer responsibilities

## Frontend

The frontend owns presentation only.

Responsibilities include:

- workspace interface
- investigation thread
- notebook
- quiz interface
- router trace rendering
- streaming responses
- citation display
- fetch-based SSE consumption for index, ask, and quiz streams

The frontend never:

- parses files
- accesses SQLite
- communicates directly with GPT-5.6

In local development, Vite proxies frontend API requests to the backend on `127.0.0.1:8000`.

---

## Backend

The backend coordinates the complete workflow.

Responsibilities include:

- indexing
- retrieval
- orchestration
- notebook persistence
- sandbox execution
- communication with GPT-5.6

The backend is the application's single source of truth.

---

## Local Retrieval

The retrieval layer searches locally indexed content.

Its responsibilities are defined in `techstack.md` and `dataflow.md` and include:

- keyword search
- semantic search
- citation resolution

Retrieval always executes locally.

---

## Python Sandbox

The sandbox executes generated Python safely against local datasets.

Responsibilities include:

- executing generated analysis code
- producing plots
- capturing stdout/stderr
- saving generated artifacts

Execution occurs entirely on the student's machine.

---

## Storage

Persistent storage contains:

- indexed metadata
- document chunks
- dataset profiles
- notebook artifacts
- concept log
- quiz history

The storage schema is defined exclusively in `schemas.md`.

Runtime schema initialization includes SQLite migrations and schema-version tracking; see `schemas.md` for contract note and `backend/db.py` for shipped bootstrap behavior.

---

# 4. Runtime lifecycle

## Startup

Application launch follows this sequence:

1. Backend starts.
2. Startup validation checks env, registry writes, SQLite writes, sandbox readiness.
3. SQLite opens.
4. Frontend connects.
5. Previous workspace metadata is restored.

---

## Workspace indexing

Workspace creation follows the pipeline defined in `dataflow.md`.

Conceptually:

```
Folder

↓

Discovery

↓

Parsing

↓

Indexing

↓

Workspace Brief

↓

Ready
```

---

## Question processing

Every user question follows the same high-level lifecycle:

```
Question

↓

Backend orchestration

↓

Local retrieval and/or analysis

↓

GPT-5.6 reasoning

↓

Streaming response

↓

Local persistence
```

The exact execution flow is defined in `dataflow.md`.

---

# 5. Component relationships

```
Frontend
      │
      ▼
Backend
      │
 ┌────┴───────────────────────┐
 │                            │
 ▼                            ▼
Local Retrieval         Python Sandbox
 │                            │
 └──────────────┬─────────────┘
                ▼
            Local Storage

                │
                ▼
             GPT-5.6
```

The backend is the only component permitted to communicate with GPT-5.6.

---

# 6. Local-first boundary

Fieldnotes follows a local-first architecture.

The following remain on-device:

- source files
- indexes
- embeddings
- notebook
- generated scripts
- generated charts
- concept log
- quiz history

Only the task-scoped information defined in `dataflow.md` and `rule.md` is sent to GPT-5.6.

This boundary is the primary privacy guarantee of the system.

---

# 7. Failure strategy

The system is designed to degrade gracefully.

Examples:

- If semantic retrieval is unavailable, fallback behavior is defined in `techstack.md`.
- If Python execution fails, sandbox behavior follows `rule.md`.
- If indexing partially fails, successfully parsed files remain usable.

Failure handling should preserve the workspace whenever possible rather than aborting the session.

---

# 8. Architectural principles

The architecture follows these principles:

1. Local-first by default.
2. Single backend authority.
3. Contract-first development.
4. Observable agent behavior.
5. Persistent learning workspace.
6. Clear separation of responsibilities.
7. Minimal cloud dependency.
8. Human-inspectable outputs.

---

# 9. Relationship to other documents

| Document | Responsibility |
|-----------|----------------|
| prd.md | Product vision and requirements |
| techstack.md | Technology choices and dependencies |
| dataflow.md | Runtime execution flow |
| schemas.md | Contracts, APIs, events, database schema |
| design.md | User interface and UX |
| implementation-phases.md | Build order |
| rule.md | Engineering constraints |
| tracker.md | Project progress |

This document intentionally introduces **no new contracts**. It exists only to explain how the documented components fit together.
