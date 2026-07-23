# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-23.

## Identity

- Agent/task owner: Claude — `/goal` Priorities 1 and 2. **Priority 1 (Deterministic Job Compiler) is MERGED** into `main` via PR #89 (`93f96ff`). **Priority 2 (customer-optional intake bridge) is implemented on branch `agent/claude/intake-bridge`** (draft PR pending).
- Branch/HEAD: `agent/claude/intake-bridge`, off `main` at `93f96ff`. **Migration head advances to `038_intake_vehicle_draft`.**
- Working directory: primary repo checkout (`origin` = the optimusOS GitHub repository).

## Context

Two `/goal` slices this session:
1. **Priority 1 — Deterministic Job Compiler (MERGED, PR #89).** Standalone no-OpenAI service compiling an approved diagnostic finding into a priced draft job (labor lines, part needs at customer price, work-order tasks, totals). Idempotent on the computed output, owner-gated, never releases/orders/pays. ADR-025. All 6 CI checks green.
2. **Priority 2 — customer-optional intake bridge (this branch).** Done additively per `/goal` — **`vehicles.customer_id` is NOT made nullable** (the estimate/work-order/invoice invariants depend on it). Instead the existing `intake_requests` **draft** entity is extended with structured VIN-decoded vehicle fields so it holds an identified vehicle before a customer exists, and conversion is made atomic + attach-aware. ADR-026.

## Active task (Priority 2 — implemented, verified locally, reviewed on-branch)

Customer-optional intake bridge. Surface and files:

- `app/db_models.py` + `alembic/versions/038_intake_vehicle_draft.py` — seven nullable vehicle columns on `intake_requests` (`vehicle_vin`, `vehicle_year/make/model/trim/engine/drivetrain`).
- `app/models.py` — `IntakeVehicleDraft` mixin (VIN validator requiring a full 17-char VIN or blank) on `IntakeRequestBase`/`IntakeRequestUpdate`/`IntakeRequestConvertRequest`; convert gains `customer_id`.
- `app/customer_store.py` / `app/vehicle_store.py` — new backward-compatible `commit: bool = True` parameter for atomic composition.
- `app/intake_store.py` — draft-field persistence; atomic `convert_intake_request` (`_resolve_vehicle_fields` merges draft + payload override; `_resolve_customer` attaches to an existing same-shop non-archived customer or signals new-customer creation; single final commit; dup-VIN/double-conversion → 409; no orphan on failure).
- `app/static/index.html` / `app.js` — Service Desk intake form gains VIN + Decode-VIN + structured vehicle fields; convert form gains an optional existing-customer-ID attach input.
- Tests: `tests/test_intake_bridge_api.py` (12), `tests/e2e/test_intake_vehicle_migration.py` (real-Postgres round-trip), `tests/test_official_ui.py` (+1 UI wiring test).
- Docs: ADR-026 (`DECISIONS.md`), `CURRENT_STATE.md` section, this handoff, `KNOWN_ISSUES.md` entry.

Out of scope (deliberately not done): making `vehicles.customer_id` nullable (forbidden by `/goal`; not needed); a full customer-typeahead picker in the convert UI (v1 uses a numeric existing-customer-ID input); auto-decoding a VIN on paste.

## Verified baseline

- `git diff --check` clean; `ruff format --check app tests`, `ruff check app tests`, `pyright` — all clean.
- `node --check app/static/app.js` — clean.
- `pytest --ignore=tests/e2e` — **832 passed, 2 skipped** at the first commit; +1 (partial-VIN regression) after the review fix. No pre-existing test weakened.
- `alembic heads` — single head `038_intake_vehicle_draft`.
- **Real Postgres 16 round-trip verified locally** (`tests/e2e/test_intake_vehicle_migration.py`): 037→038 adds the seven columns, downgrade removes them, re-upgrade restores.
- `tests/test_role_isolation.py` green (intake routes unchanged, owner/manager-gated).

## Evidence (key acceptance tests, `tests/test_intake_bridge_api.py`)

- Draft holds VIN-decoded vehicle before any customer/vehicle exists: `test_draft_holds_vin_decoded_vehicle_before_customer` (asserts zero `Customer`/`Vehicle` rows created by drafting).
- Conversion defaults the vehicle from the draft: `test_convert_uses_stored_vehicle_fields`; payload overrides it: `test_convert_payload_overrides_draft_vehicle`; customer-only when no vehicle: `test_customer_only_conversion_when_no_vehicle`.
- Attach to an existing customer (no new customer row): `test_convert_attaches_to_existing_customer`. Cross-shop customer rejected (422, draft untouched): `test_convert_rejects_cross_shop_customer`. Archived customer rejected (409): `test_convert_rejects_archived_customer`.
- No orphan on duplicate VIN (409, customer count unchanged): `test_convert_rejects_duplicate_vin_without_orphaning_customer`. Concurrent VIN-race → 409 + rollback: `test_convert_vin_race_maps_to_conflict_without_orphan`. Double-conversion blocked (409): `test_double_conversion_is_rejected`.
- Draft VIN validation: invalid character and partial-length both rejected at draft time: `test_draft_rejects_invalid_vin`, `test_draft_rejects_partial_vin`. Draft vehicle-field round-trip: `test_update_draft_vehicle_fields_round_trip`.
- Migration: `tests/e2e/test_intake_vehicle_migration.py` proves 037→038 adds the seven columns, downgrade removes them, and re-upgrade restores, on real Postgres 16.

## Reviews (on-branch)

- **Security (optimus-security-reviewer): PASS** on cross-tenant isolation of the attach-to-existing-customer path, authorization gating, and orphan/duplicate-VIN/silent-merge prevention. No Critical/High. Low nits (optional): cross-shop/missing `customer_id` returns 422 rather than 404 (accepted — it's invalid conversion input, and the message is identical for missing-vs-cross-shop so there's no enumeration signal); a pre-existing VIN concurrency race surfaces as 503.
- **Correctness (optimus-reviewer): one issue fixed** — the draft VIN validator originally allowed a partial (1–16 char) VIN, which conversion's `normalize_vin` (exactly 17) would then reject with a 422; fixed so the draft requires a full 17-char VIN or blank (`test_draft_rejects_partial_vin`).

## Unverified

- Full Docker/Playwright authenticated E2E of the new intake UI was not run in a live browser this session; verified via `node --check`, the `tests/test_official_ui.py` markup-wiring test, and static review. CI's authenticated e2e job covers the app end to end.

## Unrelated preexisting changes

- The `commit=False` path added to `create_customer`/`create_vehicle` also fixes a **pre-existing latent orphan-customer bug** in the prior always-commit conversion flow (a vehicle-creation failure after the customer was already committed). This is a real improvement, disclosed here, scoped to the same conversion path.

## Blockers and risks

- No engineering blocker. Additive and revert-safe: revert the commit(s) + `alembic downgrade 037_job_compilations`.
- Merge coordination: sync `main` and re-run gates before merge.

## Exact next task

1. Push `agent/claude/intake-bridge`, open a draft PR, confirm CI green, mark ready, merge, sync `main`.
2. Natural follow-ups (each its own slice): release a Job Compiler compiled draft into the canonical Estimate/WorkOrder/Invoice via the existing owner-approved approval flow; per-service parts picker in the compile UI; a full customer-typeahead picker in the intake convert form; auto-decode VIN on paste at intake; surfacing diagnostic severity/confidence in reports.
