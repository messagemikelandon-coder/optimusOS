# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-23.

## Identity

- Agent/task owner: Claude — Deterministic Job Compiler (`/goal` Priority 1): compile an approved diagnostic finding into a priced draft job (labor, part needs, work-order tasks, totals) through one deterministic, no-OpenAI/no-paid-call service.
- Branch/HEAD: `agent/claude/job-compiler`, off `main` at `e14de1a`. Two commits: `822ec3f` (backend + tests + migration) and `6db7634` (frontend UI + UI test). **Migration head advances to `037_job_compilations`.**
- Working directory: primary repo checkout (`origin` = the optimusOS GitHub repository).

## Context

Prior sessions deferred the "Job Compiler" because the existing estimate-creation path runs through the billable AI research orchestrator (`app/orchestrator.py`), which `/goal`'s no-billable-AI rule forbids. `/goal` Priority 1 explicitly asks for a **deterministic** compiler that must not require OpenAI. This slice builds exactly that as a **separate standalone domain** (ADR-025), not the AI estimate path. Reusing the AI `EstimateResponse` was rejected because its `SelectedPart` model mandates a retailer `url` that in-house catalog parts do not have (reusing it would mean fabricating URLs).

## Active task (implemented, verified locally, awaiting review/merge)

Deterministic Job Compiler. Surface and files:

- `app/job_compiler.py` — `compile_job` / `get_compiled_job` / `list_compiled_jobs` / `list_compiled_job_events`. Deterministic expansion of an owner-validated `JobCompilationRequest` into labor lines, aggregated part needs (customer `unit_price` only; `unit_cost` never read), work-order task descriptors, reconciled `Decimal` totals. Idempotent via `content_hash`; supersedes on changed inputs; row-locks the finding.
- `app/models.py` — `JobCompilation*` request/read models (`JobCompilationRequest`, `JobCompilationServiceInput`, `JobCompilationPartInput`, `CompiledJob*`).
- `app/db_models.py` + `alembic/versions/037_job_compilations.py` — `job_compilations`, `job_compilation_events`.
- `app/main.py` — 4 owner/manager-gated routes (`OwnerAuthContextDep`): `POST /api/diagnostic-findings/{id}/compile-job`, `GET /api/job-compilations`, `GET /api/job-compilations/{id}`, `GET /api/job-compilations/{id}/events`.
- `app/static/{index.html,app.js,styles.css}` — owner/manager-only "Compile job from finding" panel in the diagnostics view.
- Tests: `tests/test_job_compiler_api.py` (12), `tests/e2e/test_job_compilation_migration.py` (real-Postgres round-trip), `tests/test_official_ui.py` (+1 UI wiring test).
- Docs: ADR-025 (`docs/context/DECISIONS.md`), `CURRENT_STATE.md` section, this handoff, `KNOWN_ISSUES.md` entry.

Out of scope (deliberately not done): releasing a compiled draft into the canonical Estimate/WorkOrder/Invoice via the existing owner-approved approval flow (the compiler produces its deterministic input; the release step is the next slice); AI-proposed compile inputs; a per-service parts picker in the UI (the API fully supports parts and is tested; v1 UI covers labor services + fees); optional severity-priority ordering.

## Verified baseline

- `git diff --check` clean; `ruff format --check app tests`, `ruff check app tests`, `pyright` — all clean (0 errors).
- `node --check app/static/app.js` — clean.
- `pytest --ignore=tests/e2e` — **819 passed, 2 skipped** (+12 API tests, +1 UI test; no pre-existing test weakened).
- `tests/test_role_isolation.py`, `tests/test_capability_gate_safeguards.py` — green (new routes auto-classified owner-gated; no `CapabilityGateMode.ENFORCE`).
- `alembic heads` — single head `037_job_compilations`.
- **Real Postgres round-trip verified locally on Docker Postgres 16** (`tests/e2e/test_job_compilation_migration.py`): 036→037 creates `job_compilations`/`job_compilation_events` + the status CHECK, downgrade to 036 removes both, re-upgrade restores.
- OpenAPI builds; 4 new paths; `CompiledJobPartLine` exposes `unit_price` only (no `unit_cost`).

## Evidence (key acceptance tests)

- Deterministic reconciliation: `test_compile_produces_labor_parts_tasks_totals`, `test_compile_with_fees_reconciles` (labor 1.5h×$120=$180; parts $48×2=$96; supplies 5%=$9; tax 8%=$7.68; total $292.68).
- Idempotency: `test_recompile_identical_inputs_is_idempotent` (same id, one row). Supersession/revisions: `test_recompile_changed_inputs_supersedes_and_revisions` (`superseded_by_id` set, one active draft, events compiled/superseded/recompiled). Changed diagnosis forces a revision: `test_changed_diagnosis_forces_new_revision`.
- Safeguards: rejects finding without conclusion / archived finding / part without customer price; rejects cross-shop part (422) and cross-shop finding (404); aggregates a duplicate part across services; creates no Estimate/Notification (`test_compile_creates_no_estimate_or_notification`).

## Unverified

- Full Docker/Playwright authenticated E2E of the compile UI was **not** run in a live browser this session; verified via `node --check`, the `tests/test_official_ui.py` markup-wiring regression test, and static review (the repo's established bar for a slice without a live browser). CI's authenticated e2e job covers the app end to end.
- Independent correctness + security reviews were run on-branch (optimus-reviewer / optimus-security-reviewer); apply any findings before merge.

## Unrelated preexisting changes

- None. Every change is scoped to this slice: additive migration `037` (two new tables), one new service, four new owner-gated routes, new UI panel, new tests, new ADR/doc updates. No existing route's default behavior changed.

## Blockers and risks

- No engineering blocker. Additive and revert-safe: revert the two commits + `alembic downgrade 036_diagnostic_evidence`.
- Merge coordination: sync `main` and re-run gates before merge (other agent worktrees may have moved `main`).

## Exact next task

1. Push `agent/claude/job-compiler`, open a draft PR, confirm CI green, address any review findings, mark ready, merge, and sync `main`.
2. `/goal` Priority 2 — customer-optional intake bridge. Per `/goal`, do **not** make `vehicles.customer_id` nullable directly. Build a bounded **draft intake entity** holding VIN-decoded vehicle data + complaint before a customer exists, with atomic customer-attachment/conversion into the canonical vehicle, preventing duplicate VINs/conversion, silent merges, orphan records, and cross-shop attachment, and preserving estimate/work-order/invoice invariants. If unsafe to do fully, produce the ADR + migration plan + invariants + failing tests instead of forcing the nullable-FK change. Note there is an existing `intake_requests` table (`app/intake_store.py`, migration `014`) and a VIN-decode endpoint (`POST /api/vehicles/decode-vin`, PR #85) to build on.
3. Job Compiler follow-ups (each its own slice): release a compiled draft into the canonical Estimate/WorkOrder/Invoice through the existing approval flow; per-service parts picker in the compile UI; AI-proposed compile inputs (validated deterministically); severity-priority ordering.
