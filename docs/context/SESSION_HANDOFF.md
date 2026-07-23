# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-23.

## Identity

- Agent/task owner: Claude — `/goal` release + AI program. **Canonical release bridge (P1) is implemented on branch `agent/claude/release-bridge`** (draft PR pending). Builds on the merged Job Compiler (PR #89, migration 037) and intake bridge (PR #90, migration 038).
- Branch/HEAD: `agent/claude/release-bridge`, off `main` at `9b4b2fc`. Commit `4eca5d5`. **Migration head advances to `039_job_compilation_release`.**
- Working directory: primary repo checkout (`origin` = the optimusOS GitHub repository).

## Context

This `/goal` has three slices: **P1** canonical release bridge (this branch), **P2** recommendation-only AI proposing Job Compiler inputs (not started), **P3** same-shop customer typeahead for draft conversion (not started). P1 completes the compiler→estimate connective step that ADR-025 deferred, reusing the estimate/approval/work-order/invoice pipeline rather than building a parallel record.

## Active task (P1 — implemented, verified locally, reviewed on-branch)

Canonical release bridge (ADR-027). Surface and files:

- `app/job_release.py` — `release_job_compilation` + `_build_estimate_response`/`_build_estimate_request` (deterministic `EstimateResponse` from the compilation snapshot; confidence/severity/conclusion preserved into the research bundle).
- `app/estimate_store.py` — `create_estimate_from_payload` (deterministic, no-orchestrator estimate persistence reusing `_validate_generated_estimate`/snapshot/numbering/content-hash; `commit=False` capable).
- `app/models.py` — `SelectedPart.url` and `EstimateRequest.location` made optional (backward compatible); `CompiledJobRead.released_estimate_id`; `JobCompilationReleaseResponse`.
- `app/db_models.py` + `alembic/versions/039_job_compilation_release.py` — `released_estimate_id`/`released_at`/`released_by_user_id` on `job_compilations`; `job_compilation_events` CHECK widened to allow `released`.
- `app/orchestrator.py` — defensive guard for the now-optional `request.location` (AI path unchanged).
- `app/main.py` — `POST /api/job-compilations/{id}/release` (owner/manager-gated).
- `app/static/index.html`/`app.js`/`styles.css` — "Release to estimate" button + in-house-catalog part display.
- Tests: `tests/test_job_release_api.py` (7), `tests/e2e/test_job_compilation_release_migration.py` (real-Postgres round-trip), `tests/test_official_ui.py` (+1 UI wiring test).
- Docs: ADR-027 (`DECISIONS.md`), `CURRENT_STATE.md` section, this handoff, `KNOWN_ISSUES.md` entry.

Out of scope (deliberately not done): regenerating a released estimate as a new revision of the same estimate (each compilation revision → at most one new estimate); auto-sending for customer approval (release creates a DRAFT only); P2 (AI) and P3 (customer picker).

## Verified baseline

- `git diff --check` clean; `ruff format --check app tests`, `ruff check app tests`, `pyright` — all clean.
- `node --check app/static/app.js` — clean.
- `pytest --ignore=tests/e2e` — **842 passed, 2 skipped** (+7 release API tests, +1 UI test; no pre-existing test weakened, incl. all estimate/invoice/approval tests with the optional url/location).
- `alembic heads` — single head `039_job_compilation_release`.
- **Real Postgres 16 round-trip verified locally** (`tests/e2e/test_job_compilation_release_migration.py`): 038→039 adds the three columns + widens the event CHECK to allow `released`; downgrade reverses; re-upgrade restores.
- `tests/test_role_isolation.py` green (the new release route is owner/manager-gated).

## Evidence (key acceptance tests, `tests/test_job_release_api.py`)

- Release creates a real DRAFT estimate carrying the compiled totals/labor/customer-priced parts (no `unit_cost`, no retailer URL): `test_release_creates_draft_estimate`.
- Idempotent (one estimate, one `released` event on re-release): `test_release_is_idempotent`.
- Rejects a superseded/stale compilation (422): `test_release_rejects_superseded_compilation`. Cross-shop compilation is not found (404, no estimate leaked): `test_release_rejects_cross_shop_compilation`.
- Preserves severity/confidence into the estimate research bundle: `test_release_preserves_severity_and_confidence`.
- The released estimate is a real canonical estimate — it sends through the existing approval pipeline (DRAFT → AWAITING_APPROVAL): `test_released_estimate_flows_through_approval_pipeline`.
- Migration: `tests/e2e/test_job_compilation_release_migration.py` proves the 038↔039 round-trip and the `released` CHECK value on real Postgres.

## Unverified

- Full Docker/Playwright authenticated E2E of the release UI was not run in a live browser this session; verified via `node --check`, the `tests/test_official_ui.py` markup-wiring test, and static review. CI's authenticated e2e job covers the app end to end.

## Unrelated preexisting changes

- None. Every change is scoped to the release bridge. The `SelectedPart.url`/`EstimateRequest.location` optional change is a deliberate, backward-compatible enabler (the AI create-input `EstimateRecordBase.location` stays required; the AI path still sets `SelectedPart.url`); the `orchestrator.py` guard is defensive for that change.

## Blockers and risks

- No engineering blocker. Additive and revert-safe: revert the commit(s) + `alembic downgrade 038_intake_vehicle_draft`.
- Merge coordination: sync `main` and re-run gates before merge.

## Exact next task

1. Push `agent/claude/release-bridge`, open a draft PR, confirm CI green, address any review findings, mark ready, merge, sync `main`.
2. `/goal` P2 — recommendation-only AI: a provider-neutral interface proposing structured Job Compiler inputs (services with labor-hour suggestions, part categories, evidence, assumptions, confidence, questions) from a diagnostic finding's evidence. **Draft-only**: deterministic validation + owner approval mandatory; AI never invents diagnosis/VIN/prices/availability/labor truth/approval/payment; no autonomous estimate/WO/invoice writes; CI uses deterministic fakes (no paid/live call); record model/prompt-version/validation/actor/disposition without secrets; test malformed output, prompt injection, unsupported claims, timeout, provider failure, duplicates, cross-shop. Build on the existing provider-neutral OpenAI service pattern (`app/services/openai_web.py`) but keep the AI output strictly a proposal that feeds the deterministic `JobCompilationRequest` validation.
3. `/goal` P3 — same-shop customer typeahead for the intake convert flow (bounded search, stable order, hard limits, tenant isolation, accessible), replacing the numeric existing-customer-ID input; preserve atomic conversion + duplicate-VIN protection.
