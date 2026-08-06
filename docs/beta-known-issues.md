# Fieldnotes Beta Known Issues

Version: `1.0.0-beta.1`

Only issues affecting correctness, data integrity, security, or installation should block `v1.0.0`.

## Critical

None confirmed.

## High

### H-1. [RESOLVED 2026-08-06 — working as intended, not a bug] Real `OPENAI_API_KEY` takes precedence over `FIELDNOTES_USE_FAKE_LLM`

- Category: correctness / test determinism (reclassified from "bug" to "known tradeoff")
- Decision: a real configured key overriding `FIELDNOTES_USE_FAKE_LLM` is the **intended** behavior — a deliberate safety net against a stale fake-mode flag silently serving fake responses in a real deployment that has since been given a real key. Confirmed by a pre-existing, deliberately-named test, `tests/test_beta_reliability.py::test_openai_api_key_takes_precedence_over_fake_flag`, which a fix attempt during this session broke (see below). User decision 2026-08-06: leave this behavior as-is; do not make `FIELDNOTES_USE_FAKE_LLM` override a live key.
- What this means in practice: `tests/test_flashcards.py` (`test_review_flashcard_applies_sm2_and_updates_mastery`, `test_generate_flashcards_returns_verified_citations`, `test_low_mastery_triggers_more_flashcard_generation`) will continue to nondeterministically attempt real API calls and time out (~500s+) in any environment with a real `OPENAI_API_KEY` present (e.g. this dev sandbox's `.env`), **even though the test explicitly sets `FIELDNOTES_USE_FAKE_LLM=1`**. This is expected, not a regression, in any future run.
- Fix history (for context, not action): a fix was attempted — `determine_llm_mode()` checking `FIELDNOTES_USE_FAKE_LLM == "1"` before checking for a live key, with `apply_startup_llm_mode()` delegating to it. Isolated verification looked clean (5 runs of `tests/test_flashcards.py`, real-API timeouts eliminated), but the full suite then failed the precedence test above. Reverted; `backend/config.py`'s `determine_llm_mode`/`apply_startup_llm_mode` are back to their pre-session form.
- If test determinism for flashcards ever needs to be fixed without touching this precedence decision: the correct mechanism is dependency-injecting/mocking the LLM client directly in tests instead of relying on env-var auto-detection (`FakeLLMClient()` passed explicitly rather than resolved via `determine_llm_mode()`) — a larger change touching every LLM-touching test, not scoped or started.
- Workaround: unset `OPENAI_API_KEY` before running the test suite locally if deterministic flashcards test runs are needed.
- Blocking status: no — not a bug, closed.

### H-2. Study plan generation has no cap on plan horizon, and item IDs use a collision-prone 32-bit truncated UUID — together these cause intermittent `UNIQUE constraint failed` errors

**Recognition signature — if you hit this, it's H-2, not a new bug:** `tests/test_flashcards.py::test_low_mastery_triggers_more_flashcard_generation` (or any `/study-plans` call with a far-future `exam_date`) fails with `sqlite3.IntegrityError: UNIQUE constraint failed: study_plan_items.id`, raised from `insert_study_plan_item` (`backend/storage/study.py`) via `generate_study_plan` (`backend/services/planner.py:240`), surfaced to the API caller as a generic 500 `{"code": "DATABASE_ERROR", "message": "Workspace data is unavailable right now."}`. It will not reproduce every run — see probability below. Do not re-investigate from scratch; this entry already has the root cause and the math.

- Category: correctness / resource bounds
- Reproducibility: intermittent (~8% per call with the test's `exam_date="2099-01-01"` fixture, confirmed both mathematically and empirically — 1 failure in 5 isolated repro runs during triage, consistent with the estimate below), whenever the exam date is far in the future. Normally masked by H-1 (see H-1 — a real key overriding `FIELDNOTES_USE_FAKE_LLM` is the confirmed intended behavior, not something being fixed): `test_low_mastery_triggers_more_flashcard_generation` usually fails on a ~500s LLM timeout before ever reaching `/study-plans`, so this code path rarely runs to completion. Found during a temporary, since-reverted attempt to change H-1's behavior — with `FIELDNOTES_USE_FAKE_LLM` briefly actually honored during that attempt, this test ran to completion enough times during triage to expose H-2 independently. Still possible to hit intermittently in normal operation whenever the real-API call happens to complete within timeout instead of hanging.
- Root cause has two independent parts — a fix needs **both**, not either:
  1. **Unbounded horizon (the trigger):** `generate_study_plan()` (`backend/services/planner.py:144`) computes `total_days = max((end - start).days, 1)` with no upper bound. `exam_date="2099-01-01"` is ~26,446 days out; at `hours_per_day=1.0` that's `total_minutes ≈ 1,586,760`, which the scheduling loop (`backend/services/planner.py:225-240`) fills at ≤60 minutes/day, producing roughly 13,000+ `study_plan_items` rows per topic (~26,000+ total across the test's 2 topics). This alone is a real user-facing bug independent of the ID collision below: any real user picking a distant exam date gets either a many-thousand-row "plan" or the request failure described here — neither is reasonable product behavior.
  2. **Collision-prone primary key (the mechanism):** each item's id is `f"item_{uuid4().hex[:8]}"` — only 32 bits of entropy, no uniqueness retry, no exception handling around the `INSERT`. At ~26,000 rows in one call, the birthday-paradox collision probability is ≈8% (`1 - exp(-n²/2^33)` at n≈26,434). **Capping `total_days` alone narrows the odds but does not eliminate the collision class** — the same 32-bit id space will resurface this exact failure at smaller scale under enough cumulative rows or concurrent plan generation (e.g. many workspaces, or many plans in one workspace, sharing the birthday-paradox math at a longer time horizon rather than a single large call).
- Separately (found while reading the loop, not yet confirmed as independently triggering, worth checking during the fix): when `find_day_for` returns a day whose capacity is already exhausted, the fallback branch (`backend/services/planner.py:230-236`) advances `schedule_index` but reuses the stale `day_iso` computed before the advance, force-allocating anyway.
- Workaround: none at the application level; avoid picking exam dates more than a few months out
- Planned fix — both parts required:
  1. Cap `total_days`/`total_minutes` to something sane regardless of exam date (e.g. a few hundred days, with remaining topics rolled forward or summarized rather than scheduled minute-by-minute out to the exam date).
  2. Replace `uuid4().hex[:8]` with a full `uuid4()` (128 bits, collision probability negligible at any realistic row count) for `study_plan_items.id` — and, since (1) doesn't fully rule out (2) recurring at scale, also either handle `IntegrityError` on insert with a regenerate-and-retry, or rely on the widened id space alone if that's judged sufficient.
  - Out of scope for this session's Phase 1-3 work — `backend/services/planner.py` was not touched by any change made this session.
- Target release: before `v1.0.0` — this is a real user-facing correctness bug, not test-only
- Blocking status: not blocking current Phase 3 architecture work; should be triaged as its own fix

## Medium

### M-1. No packaged desktop installer

- Category: installation
- Reproducibility: always
- Impact: beta users must install Python and Node.js manually
- Workaround: follow [installation.md](installation.md)
- Planned fix: package distribution after beta validation
- Target release: post-`v1.0.0`
- Blocking status: no, if onboarding remains clear

### M-2. Offline smoke mode can be mistaken for full product evaluation

- Category: documentation
- Reproducibility: sometimes
- Impact: users may validate fake LLM mode instead of live answer quality
- Workaround: use live mode with `OPENAI_API_KEY` for product evaluation
- Planned fix: keep beta onboarding explicit about live mode versus smoke mode
- Target release: `v1.0.0`
- Blocking status: no

### M-3. Live-API-gated tests error instead of skipping when a dev sandbox has a real key but no network route

- Category: testing infrastructure
- Reproducibility: always, in a sandboxed dev environment with a real `OPENAI_API_KEY` in `.env` but no outbound network access
- Impact: `tests/test_live_responses_api_integration.py::test_live_responses_api_request_succeeds` is decorated `@unittest.skipUnless(OPENAI_API_KEY set)`. `load_project_dotenv()` (`backend/config.py:34`) loads `.env`'s real key into the environment via `setdefault`, so the skip condition is satisfied and the test attempts a real call, which then times out rather than being skipped. Confirmed root cause during Phase 1 verification, 2026-08-06; `.env` is gitignored and not committed, so this is a local sandbox condition, not a leaked credential.
- Workaround: unset `OPENAI_API_KEY` (or point `.env` at a placeholder) before running tests offline
- Planned fix: none planned — working as designed given the key is present; consider gating the skip condition on network reachability too if this recurs in CI
- Target release: n/a
- Blocking status: no

### M-4. `google_drive_credentials.user_id` has no foreign key to `users.user_id`

- Category: data integrity
- Reproducibility: always (schema gap, not a runtime error)
- Impact: nothing enforces that a `google_drive_credentials` row corresponds to a real `users` row, so a deleted user's stored Drive tokens can be orphaned instead of cascade-deleted. Every other cross-table `user_id` reference in the registry schema (`workspace_members.user_id`) has this FK; this one was missed in `registry_0001`.
- **Not a one-line fix** — attempted during Phase 1 close-out (2026-08-06) as `registry_0003`, verified empirically against `test_google_drive_integration.py`, and reverted after it broke `test_status_reports_connected_once_credentials_saved` with `sqlite3.IntegrityError`. Root cause: `users` is only ever populated by `workspace_manager.py` on workspace creation (for the creator) and by `_ensure_local_admin()` — never during the plain OAuth login/`purpose=drive` callback (`backend/auth/router.py:279`, which calls `save_drive_credentials()` directly). Any user who connects Drive without having created a workspace (e.g. a workspace member who isn't the creator) has no `users` row, so adding the FK as schema-only would reject their credentials save in production.
- Correct scope: (1) the FK migration itself (straightforward, `batch_alter_table` + `create_foreign_key`, `ondelete="CASCADE"` to match `workspace_members.user_id`'s pattern), **plus** (2) upserting into `users` on every successful OAuth login in `backend/auth/router.py`'s callback handler, not just on workspace creation. Both parts are required together — shipping (1) without (2) reproduces the break described above.
- Planned fix: bundle into Phase 3 backend-architecture work (natural fit alongside the auth/router.py and main.py touch points already planned there)
- Target release: post-Phase 1, during Phase 3
- Blocking status: no — not currently causing incorrect behavior, just missing enforcement

## Low

### L-1. `run.sh` is Unix-only

- Category: documentation
- Reproducibility: always on Windows
- Impact: Windows users cannot use convenience launcher
- Workaround: start backend with `python -m uvicorn ...` and frontend with `npm run dev`
- Planned fix: docs already clarified; no code change planned
- Target release: post-`v1.0.0`
- Blocking status: no

### L-2. Published docs lacked single external beta path

- Category: usability
- Reproducibility: always before beta onboarding doc
- Impact: users had to jump between README, installation guide, quickstart, and release notes
- Workaround: use [beta-onboarding.md](beta-onboarding.md)
- Planned fix: completed in beta program 1
- Target release: fixed in `1.0.0-beta.1`
- Blocking status: no

### L-3. Published docs mixed `python` and `python3`

- Category: documentation
- Reproducibility: always before wording cleanup
- Impact: cross-platform setup looked inconsistent
- Workaround: use `python` commands from onboarding and install docs
- Planned fix: completed in beta program 1
- Target release: fixed in `1.0.0-beta.1`
- Blocking status: no
