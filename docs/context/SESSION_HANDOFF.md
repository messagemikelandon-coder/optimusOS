# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-23.

## Identity

- Agent/task owner: Claude — `/goal` release + AI program. **Canonical release bridge (P1) merged** (PR #91, migration 039). **Recommendation-only AI (P2) implemented on branch `agent/claude/ai-job-proposals`** (draft PR pending). **P3 (customer typeahead) not started.**
- Branch/HEAD: `agent/claude/ai-job-proposals`, off `main` at `e419aaf`. Commits `4c76e49` (remove stray wordlist.txt) + `69a62c4` (P2). **Migration head advances to `040_job_input_proposals`.**
- Working directory: primary repo checkout (`origin` = the optimusOS GitHub repository).

## Context

Three `/goal` slices: **P1** canonical release bridge (MERGED, PR #91, ADR-027), **P2** recommendation-only AI proposing Job Compiler inputs (this branch, ADR-028), **P3** same-shop customer typeahead for the intake convert flow (not started). P2 gives shops an AI *draft* of recommended services + labor-hour estimates + part categories that feeds the deterministic compiler — the AI never invents prices/VIN/availability/approval and writes nothing autonomously.

## Active task (P2 — implemented, verified locally, reviewed on-branch)

Recommendation-only AI (ADR-028). Surface and files:

- `app/job_proposal.py` — provider-neutral `JobInputProposer` ABC + `propose`; `OpenAIJobInputProposer` (structured output, safe-failure, never called in CI); `build_job_input_proposer` factory (tests inject a fake); `validate_proposed_inputs` deterministic gate; shop-scoped `propose_job_inputs`/`list`/`get`/`set_disposition`.
- `app/models.py` — `ProposedJobInputs`/`ProposedJobService` (`extra='forbid'`; no price/VIN/availability/approval field; bounded labor-hour suggestion; generic part categories) + `JobInputProposal*` read/list/disposition models.
- `app/db_models.py` + `alembic/versions/040_job_input_proposals.py` — `job_input_proposals` audit table.
- `app/main.py` — 4 owner/manager-gated routes: `POST /api/diagnostic-findings/{id}/propose-job-inputs` (503 when unconfigured; finding loaded shop-scoped before the provider is called), `GET /api/job-input-proposals`, `GET /api/job-input-proposals/{id}`, `PATCH /api/job-input-proposals/{id}` (disposition).
- `app/static/index.html`/`app.js`/`styles.css` — "Suggest inputs (AI draft)" button populating the compile form; states the AI sets no prices; all proposal text escaped.
- Tests: `tests/test_job_proposals_api.py` (13), `tests/e2e/test_job_input_proposals_migration.py` (real-Postgres round-trip), `tests/test_official_ui.py` (+1 UI wiring test).
- Docs: ADR-028 (`DECISIONS.md`), `CURRENT_STATE.md` section, this handoff, `KNOWN_ISSUES.md` entry.

Out of scope (deliberately not done): auto-applying a proposal into a compilation/estimate (draft-only; the owner drives the deterministic compile); a second AI provider (implement the ABC); a golden/replay harness for the real provider; P3 (customer typeahead).

## Verified baseline

- `git diff --check` clean; `ruff format --check app tests`, `ruff check app tests`, `pyright` — all clean.
- `node --check app/static/app.js` — clean.
- `pytest --ignore=tests/e2e` — **858 passed, 2 skipped** (+13 API/safety tests, +1 UI test; no pre-existing test weakened).
- `alembic heads` — single head `040_job_input_proposals`.
- **Real Postgres 16 round-trip verified locally** (`tests/e2e/test_job_input_proposals_migration.py`): 039→040 adds `job_input_proposals` + the status CHECK; downgrade drops it; re-upgrade restores.
- `tests/test_role_isolation.py` green (all 4 proposal routes owner/manager-gated).
- **CI uses a deterministic fake** injected via `build_job_input_proposer`; `OpenAIJobInputProposer` with no key raises rather than calling — no paid/live call.

## Evidence (key acceptance/safety tests, `tests/test_job_proposals_api.py`)

- Schema forbids invented facts: `test_schema_forbids_injected_price_field`, `test_schema_forbids_top_level_injected_fields` (price/approved/vin rejected by `extra='forbid'`); `test_validator_rejects_malformed_payload`; `test_schema_bounds_labor_hours`.
- No provider configured is safe: `test_openai_proposer_without_key_is_unavailable`.
- Draft-only / no autonomous writes: `test_propose_persists_draft_and_creates_nothing_else` (0 Estimate, 0 JobCompilation). Prompt injection contained: `test_prompt_injection_in_evidence_cannot_trigger_autonomous_action`.
- Cross-shop finding → 404 and provider NOT called: `test_propose_cross_shop_finding_is_not_found_and_provider_not_called`. Provider failure → safe 503, nothing persisted: `test_provider_failure_is_safe_and_persists_nothing`.
- Isolation + lifecycle: `test_cross_shop_proposal_access_is_denied`, `test_list_get_and_disposition`, `test_repeated_proposals_are_independent_records`.
- Migration: `tests/e2e/test_job_input_proposals_migration.py` (real Postgres 039↔040 round-trip).

## Unverified

- Full Docker/Playwright authenticated E2E of the "Suggest inputs" UI was not run in a live browser this session; verified via `node --check`, the `tests/test_official_ui.py` markup-wiring test, and static review. CI's authenticated e2e job covers the app end to end.
- The **real** `OpenAIJobInputProposer._propose_sync` OpenAI call path is `# pragma: no cover` — never exercised in CI (no live call). Its safe-failure wrapper IS tested via the injected fake raising.

## Unrelated preexisting changes

- Commit `4c76e49` removes an empty stray `wordlist.txt` that was accidentally swept onto `main` by a `git add -A` in the release-bridge slice (commit `3c3ffde`). Benign cleanup, disclosed.

## Blockers and risks

- No engineering blocker. Additive and revert-safe: revert the commit(s) + `alembic downgrade 039_job_compilation_release`.
- Merge coordination: sync `main` and re-run gates before merge.

## Exact next task

1. Push `agent/claude/ai-job-proposals`, open a draft PR, confirm CI green, address any review findings, mark ready, merge, sync `main`.
2. `/goal` P3 — same-shop customer typeahead for the intake convert flow (`app/static` Service Desk convert form): replace the numeric existing-customer-ID input with an accessible typeahead backed by the existing `GET /api/customers?search=` (bounded search, stable order, hard limit, tenant isolation, safe empty/loading states). Preserve the atomic conversion + duplicate-VIN protection from ADR-026. Small slice.
3. Follow-ups: allow a proposal to pre-fill a compilation for one-click owner review (still deterministic-validated); a second AI provider implementing `JobInputProposer`; surfacing severity/confidence in reports.
