# Fieldnotes — Implementation Rules

**Version:** 1.0
**Date:** July 17, 2026
**Purpose:** Standing constraints for every implementation session (Codex or human). These rules are binding for all code written in this repo. When a rule conflicts with an ad-hoc idea mid-session, the rule wins; change the rule file first if it must change.
**Companions:** prd.md, techstack.md, dataflow.md, design.md, schemas.md, implementation-phases.md (all in `/docs`)

---

## R1. Document authority hierarchy

1. **schemas.md is law for data shapes.** No type, event, table, or API model may be invented, extended, or renamed in code. If a shape is missing or wrong, update schemas.md first, in its own commit, then implement.
2. **implementation-phases.md is law for sequence.** Work only on the current phase. A phase is complete only when its exit test passes — never on "mostly working."
3. **prd.md is law for scope.** Anything not traceable to an FR number or the demo plan (prd.md §11, Demo script) is out of scope by default. The non-goals list (prd.md §4, "Non-goals" sub-heading) is binding.
4. **design.md is law for UI.** Component names, states, copy voice, and color roles come from design.md — do not restyle or rename mid-build.
5. **techstack.md is law for dependencies.** No library outside techstack.md §2 without adding it to the decision log (techstack.md §8) first, with a one-line rationale.

## R2. Contract-first development

1. Backend and frontend communicate **only** through the SSE and REST contracts in schemas.md §2 and §5. Neither side may assume payload fields the contract doesn't declare.
2. All Pydantic models live in `backend/models.py`; all TypeScript types live in `frontend/src/types.ts`. Both mirror schemas.md field-for-field. No inline/anonymous shapes for contract data.
3. Every SSE payload carries its `event` discriminator. The per-answer ordering guarantee (schemas.md §2.2) is enforced by the emitter, not assumed by the consumer — the frontend must tolerate `error` at any point.
4. Responses API structured outputs are validated on receipt. Invalid intent output → fallback to `retrieve`. Quiz `source_anchor` not in the chunks table → reject and re-prompt (max 2). Starter card `file_path` not in the files table → drop the card.

## R3. Local-first boundary (non-negotiable)

1. The only data permitted in any live Responses API request: the user's question, retrieved passages, `DatasetProfile` objects, computed analysis results, concept names with their cited chunks, and the workspace inventory (names/counts/schemas/stats). **Never**: raw file bytes, full document text, raw dataset rows, embeddings, file paths outside the workspace.
2. All API calls go through one module (`backend/agent/llm.py`). No other file may import the OpenAI SDK. This makes the boundary auditable in one place.
3. `llm.py` logs every outbound payload's field names (not values) in debug mode — the network-tab verifiability claim (dataflow.md §1) must hold.
4. Embeddings are computed locally (fastembed). If the embeddings fallback triggers (BM25-only), no embedding API substitution — the fallback is BM25, not cloud embeddings.

## R4. Sandbox rules

1. Generated code executes only via `backend/sandbox/runner.py`: isolated subprocess, `timeout=15`, `resource.setrlimit` memory cap, workspace-root path jail, artifact-only writes, network blocked.
2. Generated scripts are never `exec()`'d in-process and never imported.
3. Every executed script is retained verbatim under `.fieldnotes/artifacts/` and registered in the artifacts table — the code citation chip must always resolve to the exact script that ran.
4. Sandbox failures clean up partial outputs and surface an honest non-recoverable `error` event. The shipped executor does not retry failed generated scripts.
5. matplotlib uses the Agg backend only; charts are written as PNG artifacts, never streamed as inline base64 blobs over SSE (send the `url`).

## R5. Coding standards

1. **Python:** 3.12, type hints on all public functions, `ruff` clean, no bare `except`, pathlib over os.path, f-strings. Modules match the techstack.md §6 layout — no new top-level packages.
2. **TypeScript/React:** strict mode and functional components. Shared UI is extracted where it improves clarity; the shipped frontend uses component-local and shared handwritten CSS rather than Tailwind.
3. IDs are UUID4 strings; timestamps are ISO 8601 UTC; enums are lowercase — everywhere, per schemas.md conventions.
4. No TODOs left in committed code. Either complete it, remove it, or record a material release risk in `docs/beta-known-issues.md`.
5. Config (API key, model name, ports) via environment variables read in one `backend/config.py`; `.env` is gitignored; `.env.example` is committed.

## R6. Git discipline

1. Commit at every green verification milestone and at every working sub-deliverable — small, titled commits, never a day of work in one commit.
2. `main` must pass the documented Python, frontend, and applicable release checks from a fresh local environment. `run.sh` is a Unix convenience launcher, not a cross-platform verification requirement.
3. `.gitignore` includes `.fieldnotes/`, `.env`, venvs, `node_modules`, and all artifact output. `demo_course/` **is** committed — judges need it.
4. Never commit secrets. If a key ever lands in history, rotate it immediately; do not just delete the file.

## R7. Testing rules (right-sized for 4 days)

1. Run `scripts/exit_phase0.py`, `scripts/exit_phase1.py`, the backend test suite, and frontend tests/build when their affected areas change.
2. Use `scripts/run_benchmarks.py` and `scripts/release_check.py` for release-focused regression where their prerequisites are available.
3. Keep focused unit and integration coverage for contracts, persistence, retrieval, sandbox execution, citations, and streaming behavior.
4. Use a clean workspace for demo or release-flow validation rather than relying on a warm index.

## R8. Codex session rules (submission requirements)

1. Every implementation session begins by reading the relevant current contract and architecture documents.
2. Record release or submission evidence outside the runtime documentation when it becomes available.
3. Keep decisions and deviations in version-controlled documentation when they affect a public contract or release claim.

## R9. Scope guardrails

1. Preserve public contracts, local-first data handling, persisted citations, and grounded outputs unless the product contract is deliberately revised.
2. New features require an explicit product decision; release hardening work must not silently expand scope.
3. Track meaningful unresolved release risks in `docs/beta-known-issues.md`.

## R10. Error handling and UX honesty

1. Every user-visible failure follows design.md §6 voice: what happened, then what happens next. No raw tracebacks in the UI; full tracebacks in the backend log.
2. `error` SSE events always set `recoverable` truthfully — the UI shows a retry step only when one will actually occur.
3. Parse failures are honest in the UI (`parse_status: failed` renders in the file list) — never silently skip a file; the inventory-as-audit design (design.md §3.1) depends on it.

## R11. Definition of done (per phase and overall)

A phase is done when its documented verification passes, its contracts remain accurate, and its status is reconciled in `tracker.md`.
The beta implementation is complete when its documented verification scripts pass. Public release and submission requirements are tracked in `tracker.md` and release documentation.

---

*Place this file at the repo root (and reference it from AGENTS/context config so every Codex session loads it first).*
