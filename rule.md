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
4. GPT-5.6 structured outputs are validated on receipt. Invalid intent output → fallback to `retrieve`. Quiz `source_anchor` not in the chunks table → reject and re-prompt (max 2). Starter card `file_path` not in the files table → drop the card.

## R3. Local-first boundary (non-negotiable)

1. The only data permitted in any GPT-5.6 request: the user's question, retrieved passages, `DatasetProfile` objects, computed analysis results, concept names with their cited chunks, and the workspace inventory (names/counts/schemas/stats). **Never**: raw file bytes, full document text, raw dataset rows, embeddings, file paths outside the workspace.
2. All API calls go through one module (`backend/agent/llm.py`). No other file may import the OpenAI SDK. This makes the boundary auditable in one place.
3. `llm.py` logs every outbound payload's field names (not values) in debug mode — the network-tab verifiability claim (dataflow.md §1) must hold.
4. Embeddings are computed locally (fastembed). If the embeddings fallback triggers (BM25-only), no embedding API substitution — the fallback is BM25, not cloud embeddings.

## R4. Sandbox rules

1. Generated code executes only via `backend/sandbox/runner.py`: dedicated venv, `subprocess.run`, `timeout=15`, `resource.setrlimit` memory cap, cwd = workspace dir, network blocked.
2. Generated scripts are never `exec()`'d in-process and never imported.
3. Every executed script is retained verbatim under `.fieldnotes/artifacts/` and registered in the artifacts table — the code citation chip must always resolve to the exact script that ran.
4. Exactly one automatic retry on failure, with the stderr fed back to the model. A second failure surfaces an `error` event with `recoverable: false` and honest copy (design.md §6).
5. matplotlib uses the Agg backend only; charts are written as PNG artifacts, never streamed as inline base64 blobs over SSE (send the `url`).

## R5. Coding standards

1. **Python:** 3.12, type hints on all public functions, `ruff` clean, no bare `except`, pathlib over os.path, f-strings. Modules match the techstack.md §6 layout — no new top-level packages.
2. **TypeScript/React:** strict mode, functional components, one component per file named per design.md §4 (RouterTrace, CitationChips, StarterCards, ConceptChips, NotebookCard, QuizCard, IndexProgress, LockBadge, MetricCards, InputRow). Tailwind utilities only — no CSS files beyond the Vite default.
3. IDs are UUID4 strings; timestamps are ISO 8601 UTC; enums are lowercase — everywhere, per schemas.md conventions.
4. No TODOs left in committed code. Either do it, cut it per the cut lines, or file it in `docs/deferred.md`.
5. Config (API key, model name, ports) via environment variables read in one `backend/config.py`; `.env` is gitignored; `.env.example` is committed.

## R6. Git discipline

1. Commit at every green exit-test and at every working sub-deliverable — small, titled commits (`phase2: sandbox runner with rlimits`), never a day of work in one commit.
2. `main` always runs: `run.sh` from a fresh clone + fresh `.fieldnotes/` must work at every commit on main. Risky work happens on short-lived branches.
3. `.gitignore` includes `.fieldnotes/`, `.env`, venvs, `node_modules`, and all artifact output. `demo_course/` **is** committed — judges need it.
4. Never commit secrets. If a key ever lands in history, rotate it immediately; do not just delete the file.

## R7. Testing rules (right-sized for 4 days)

1. No test framework ceremony. Each phase's **exit test lives as a runnable script** in `scripts/` (`scripts/exit_phase1.py`, `scripts/exit_phase2.sh` …) so it can be re-run after any change.
2. The Phase 2 exit test (curl trace of the Trial 4 question) is the regression test for the whole agent core — re-run it after any change to the router, prompts, sandbox, or SSE emitter.
3. Unit tests only where logic is subtle and cheap to test: anchor parsing/formatting, DatasetProfile outlier flagging, SSE event ordering. Nothing else.
4. Every dry run of the demo starts from a deleted `.fieldnotes/` — never demo against a warm index.

## R8. Codex session rules (submission requirements)

1. Every session begins by loading `/docs` context: rule.md + the phase's referenced docs, per the anchor prompts in implementation-phases.md.
2. Core functionality (Phases 1–4) is built inside Codex sessions. Record every session ID in `docs/sessions.md` as you go; run `/feedback` in the session carrying the most core functionality (expected: S2) and store that ID prominently — it is a required submission field.
3. When Codex materially accelerates something or a key decision is made, append one line to `docs/build-log.md` (`date · what · decision/acceleration`). This file becomes the README's judged narrative — write it live, don't reconstruct it on Jul 20.
4. One session = one phase goal. If a session drifts into the next phase's work before the exit test passes, stop and return to the exit test.

## R9. Scope guardrails

1. The demo-driven rule: every line of code must appear in the 3-minute demo or directly enable something that does.
2. Overruns trigger the pre-negotiated cut line for the current phase (implementation-phases.md), then the global cut order. Cutting anything on the never-cut list (router trace, sandbox execution with retained scripts, anchored citations, the amber/starter-refresh loop, the workspace brief) requires rewriting the PRD — i.e., don't.
3. New ideas mid-build go to `docs/deferred.md` with one line each. Zero exceptions during Phases 2–5.
4. Time-boxing: any single bug older than 90 minutes gets a workaround or a cut, not a heroic fix. Note it in build-log.md and move.

## R10. Error handling and UX honesty

1. Every user-visible failure follows design.md §6 voice: what happened, then what happens next. No raw tracebacks in the UI; full tracebacks in the backend log.
2. `error` SSE events always set `recoverable` truthfully — the UI shows a retry step only when one will actually occur.
3. Parse failures are honest in the UI (`parse_status: failed` renders in the file list) — never silently skip a file; the inventory-as-audit design (design.md §3.1) depends on it.

## R11. Definition of done (per phase and overall)

A phase is done when: exit test passes from a clean state · code committed on main · contracts unchanged or schemas.md updated first · build-log.md appended.
The project is done when: Phase 5 exit test passes on a clean machine · video uploaded (<3 min, public, Codex + GPT-5.6 covered in audio) · `/feedback` session ID captured · Devpost submission confirmed before 5:00 PM PT Jul 21.

---

*Place this file at the repo root (and reference it from AGENTS/context config so every Codex session loads it first).*
