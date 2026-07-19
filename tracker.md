# Fieldnotes — Progress Tracker

**Version:** live document — updated continuously per the protocol below
**Last updated:** 2026-07-18
**Companions:** rule.md (root), /docs: prd.md, techstack.md, dataflow.md, design.md, schemas.md, implementation-phases.md

---

## 0. Update protocol (binding — this is how the file "updates itself")

This file is maintained by whichever agent or human is doing the work, as part of the work. A change that doesn't update this tracker is incomplete by definition (extends rule.md R11).

**Update triggers — whenever any of these occur, update this file in the same commit:**

| Trigger | Required update |
|---|---|
| A phase deliverable is started / finished | Flip its status in §2 |
| An exit test is run | Record result + date in §2 (pass or fail — failures are logged, not hidden) |
| Work stops mid-deliverable for any reason | Add a **Partial Implementation Record** (§3) — what works, what doesn't, how to resume |
| Anything is built differently than implementation-phases.md specifies | Add a **Deviation Record** (§4) with rationale and doc impact |
| A cut line is activated | Log in §5 with what was cut and which rule authorized it |
| A blocker exceeds the 90-minute time-box (rule.md R9.4) | Log in §6 with the workaround taken |
| A schemas.md / any doc change is made (rule.md R1.1) | Note in §4 as `doc-change` type |
| A Codex session starts/ends | Append to §7 |

**Status vocabulary (use exactly these):**
`⬜ not started` · `🔵 in progress` · `🟡 partial` (stopped mid-way — must have a §3 record) · `✅ done` (exit-test-passed only) · `✂️ cut` (must have a §5 record) · `🔴 blocked` (must have a §6 record)

**Audit rule:** at the start of every session, reconcile this file against reality (git log + running the current phase's exit script). Any mismatch found is itself logged in §4 as type `audit-finding`.

---

## 1. Status dashboard

| Phase | Scope | Status | Exit test | Last run |
|---|---|---|---|---|
| 0 — Setup & unblocking | Credits, accounts, API verification, docs in repo | 🔵 in progress | Structured-output call validates against intent schema | — |
| 1 — Scaffold + ingest + index | Repo, models.py, SQLite, parsers, index, SSE | ✅ done | `scripts/exit_phase1.py` PASS | 2026-07-18 |
| 2 — Agent core (router + analyze) | Intent, tool loop, sandbox, /ask SSE, grounding | ⬜ not started | curl trace of Trial 4 question → full event sequence, chart + both chips | — |
| 3 — Workspace UI | Three panes, trace strip, chips, notebook | ⬜ not started | Full Trial 4 flow in browser incl. drawers | — |
| 4 — Brief, starters, quiz loop | Brief, concept log, quiz, loop closure | ⬜ not started | Missed answer → amber chip → starters refresh | — |
| 5 — Hardening, demo data, README | Final demo_course, errors, dry runs, README | ⬜ not started | Clean-machine clone + run.sh + demo via README only | — |
| 6 — Submission | Video, /feedback ID, Devpost form | ⬜ not started | Submission confirmed before 5:00 PM PT Jul 21 | — |

**Never-cut integrity check** (all five must remain ✅-eligible at all times — rule.md R9.2):
router trace ⬜ · sandbox with retained scripts ⬜ · anchored citations ⬜ · amber/starter-refresh loop ⬜ · workspace brief ⬜

---

## 2. Phase deliverable checklists

### Phase 0 — Setup & unblocking (⏰ credits deadline 12:00 PM PT Jul 17)
- [ ] Codex credits requested on Devpost Resources tab
- [ ] Repo created (public+license, or private+shared with testing@devpost.com, build-week-event@openai.com)
- [ ] GPT-5.6 structured-outputs + function-calling parameter names verified against current docs
- [x] All docs committed to `/docs`, rule.md at root
- **Exit test:** ⬜ — result: —
  Note: `scripts/exit_phase0.sh` runtime verification still pending; must be executed in environment where `OPENAI_API_KEY` is available.

### Phase 1 — Scaffold + ingest + index
- [x] Monorepo scaffold (backend/, frontend/, run.sh, demo_course/ stub)
- [x] backend/models.py field-for-field from schemas.md §2–§5
- [x] SQLite bootstrap from schemas.md §1 DDL
- [x] Parsers: PDF (page/block anchors) · PPTX (slide) · DOCX (paragraph) · CSV profiler w/ outlier flags
- [x] Chunking + BM25 (vector embeddings cut per §5 fallback order)
- [x] POST /index + /index/events SSE per contract
- [x] demo_course-equivalent verification workspace exercised by release script
- **Exit test:** ✅ — result: `scripts/exit_phase1.py` PASS on 2026-07-18
  Verification executed:
  - `.venv312/bin/python -m unittest tests.test_api_integration`
  - `.venv312/bin/python scripts/exit_phase1.py`

### Phase 2 — Agent core
- [ ] Intent classification + fallback-to-retrieve on invalid output
- [ ] Tool loop: search_index · run_analysis · render_chart
- [ ] Sandbox runner (venv, timeout=15, rlimits, cwd-scoped, no network, Agg PNGs)
- [ ] Schema-aware codegen + one retry with stderr fed back
- [ ] POST /ask full AskEvent sequence
- [ ] Grounding call (results + passages)
- [ ] Artifact persistence (scripts + PNGs + table rows)
- **Exit test:** ⬜ — result: —

### Phase 3 — Workspace UI
- [ ] Three-pane grid + header lock badge
- [ ] useEventSource · indexing tick-off state
- [ ] Thread: bubbles · RouterTrace · streamed prose · inline charts
- [ ] CitationChips + drawers (source + script/output)
- [ ] Left pane: file list + active highlight + ConceptChips
- [ ] Right pane: NotebookCards + empty state
- [ ] Input row + "Quiz me" button (UI only)
- **Exit test:** ⬜ — result: —

### Phase 4 — Brief, starters, quiz loop
- [ ] Brief generation + file-path validation + brief card UI
- [ ] Concept upserts per answer + amber-on-repeat
- [ ] Quiz endpoints per QuizEvent · anchor validation + re-prompt
- [ ] Quiz center-pane takeover, one question + source citation
- [ ] Loop closure: grade → chip transition → refreshed_starters → card refresh
- [ ] Quiz result as notebook artifact
- **Exit test:** ⬜ — result: —

### Phase 5 — Hardening
- [ ] Final demo_course (~15 files, anomaly legible at 1080p)
- [ ] Error states per design.md §6 · error event rendering
- [ ] 3× demo dry runs from deleted .fieldnotes/
- [ ] README incl. Codex/GPT-5.6 narrative from build-log.md
- [ ] Repo hygiene (license, .gitignore, no secrets)
- **Exit test:** ⬜ — result: —

### Phase 6 — Submission
- [ ] Demo video recorded (<3 min) + uploaded public
- [ ] /feedback session ID captured (expected session: S2)
- [ ] Devpost form drafted by 3:00 PM PT · submitted
- **Exit test:** ⬜ — result: —

---

## 3. Partial implementation records

> One record per 🟡 status. Never leave a 🟡 without a record — "how to resume" is the whole point.

**Template:**
```
### PIR-<n> · <date> · Phase <x> · <deliverable>
Works:        <what is functional, with the command/test proving it>
Doesn't:      <what is missing or broken>
Cause:        <why work stopped: time-box, dependency, cut-line pending, EOD>
Resume by:    <concrete first step, file paths, branch name>
Contract risk: <none | which schemas.md shape is half-implemented>
```

### DEV-1 · 2026-07-18 · type: deviation
Planned:   Phase 1 stack included BM25 + local vector embeddings.
Actual:    Phase 1 shipped BM25 retrieval only; release verification covers persisted chunk retrieval and citation integrity.
Reason:    Cut-order fallback consumed before release; user request forbade adding vector search in Commit 12.
Doc impact: tracker updated; contract docs reconciled to current workspace-aware API.
Approved by rule: PRD §9 cut order, implementation-phases.md §8

---

## 4. Deviation & audit log (differences from implementation-phases.md / doc set)

> Every divergence between what was planned and what was built gets a record — including doc changes (rule.md R1.1) and audit findings from the session-start reconciliation. This log is also README raw material: judges reward visible decision-making.

**Template:**
```
### DEV-<n> · <date> · type: <deviation | doc-change | audit-finding>
Planned:   <what implementation-phases.md / schemas.md / design.md said>
Actual:    <what was built instead>
Reason:    <one line>
Doc impact: <which doc was updated in which commit, or "docs updated: none — deviation accepted">
Approved by rule: <e.g., R1.1 doc-first, R9.2 cut order, or "exception — justify">
```

*(none yet)*

---

## 5. Cut-line activations

| # | Date | Phase | What was cut | Authorized by | Fallback in place |
|---|---|---|---|---|---|
| 1 | 2026-07-18 | 1 | fastembed / ChromaDB vector layer | PRD §9 cut order item 1 | BM25 retrieval active; contract + exit tests pass |

Global cut order consumed so far: **0 of 6** (embeddings → intents → drawers → highlight sync → quiz adaptivity → demo size).

---

## 6. Blockers & time-box log (rule.md R9.4)

| # | Date | Blocker | Time spent | Resolution (workaround / cut / fixed) |
|---|---|---|---|---|
| — | — | *(none yet)* | — | — |

---

## 7. Session log

| Session | Date | Phase goal | Session ID | /feedback run? | Outcome |
|---|---|---|---|---|---|
| S1 | 2026-07-18 | Phase 1 scaffold + index | — | — | complete; `scripts/exit_phase1.py` PASS |
| S2 | — | Phase 2 agent core | — | ⭐ planned | — |
| S3 | — | Phase 3 UI | — | — | — |
| S4 | — | Phase 4 brief + quiz | — | — | — |
| S5 | — | Phase 5 hardening | — | — | — |

---

## 8. Standing risks being watched

| Risk (from prd.md §13) | Status | Note |
|---|---|---|
| GPT-5.6 API parameter drift vs. assumptions | 🔵 open until Phase 0 exit test | Verify before any agent code |
| Codegen fails on demo CSVs | ⬜ | Retry path is never-cut; tune demo data in Phase 5 |
| Sandbox complexity creep | ⬜ | subprocess+rlimits only; Docker is a forbidden dependency |
| Schedule collapse | ⬜ | §5 cut order; never-cut list intact |
