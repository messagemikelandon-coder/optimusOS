# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-18.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/KNOWN_ISSUES.md`, `docs/context/GOAL_EVIDENCE_MATRIX.md`, `git log`/`git status`, `gh pr view`, `pytest -q`.

## Identity

- Updated UTC: 2026-07-18.
- Agent: Claude.
- `main` HEAD: `d2103fc` (PR #55, Phase 3 slice 4 — auto-populate `shop_id` on create).
- Current worktree/branch: `agent/claude/goal-phase3-shop-slice5-not-null`, branched from `origin/main` at `d2103fc`. Not yet committed/pushed as of this doc being written.

## Active task

This session is executing the `/goal` multi-shop-pilot roadmap (17 phases; see `docs/context/GOAL_EVIDENCE_MATRIX.md`). Phases 0-2 and Phase 3 slices 1-4 are merged. This increment combines **Phase 3 slices 5+6: a pre-flight orphan-check + the NOT NULL constraint on `shop_id`** — these were done as one PR since the entire purpose of the orphan check is to gate the NOT NULL migration; splitting them would have been an artificial separation.

Work in this increment:

1. `scripts/check_shop_id_orphans.py` (new) — standalone operational script: connects via `DATABASE_URL`, reports any `shop_id IS NULL` rows per table, exits non-zero if any found. Meant to be run by an operator against a real staging/production database before attempting migration 025, giving an actionable report ahead of time rather than discovering the problem mid-migration.
2. `alembic/versions/025_shop_id_not_null.py` (new) — constrains `shop_id` to `NOT NULL` on all 30 business tables. The migration's own `upgrade()` runs the same orphan check first and **raises a clear, itemized `RuntimeError`** (not a generic constraint-violation error) if any orphan row is found anywhere, refusing to proceed — self-defending even if the operator skipped running the script first. `downgrade()` reverts to nullable.
3. `app/db_models.py` — all 30 `shop_id` columns changed from `Mapped[int | None]`/`nullable=True` to `Mapped[int]`/`nullable=False`, matching the new DB constraint.
4. `.github/workflows/ci.yml` — added a step to the existing migration-integrity job running `scripts/check_shop_id_orphans.py` against the freshly-migrated CI database (always 0 orphans there, but this proves the script itself works on every CI run).
5. **This slice is what actually proved slices 2-4 complete, not just nominally**: turning the column NOT NULL surfaced 5 real, previously-invisible gaps that no prior test had caught, since none of them exercise a genuinely-populated database with cross-owner test scenarios or direct ORM construction:
   - `tests/test_context_api.py::create_user` — a cross-owner-isolation test helper used at ~56 call sites across ~20 test files — created a bare owner account with no `ShopMembership`. Fixed: now optionally accepts `settings` and calls `create_shop_for_new_owner`, defaulting to a fresh `Settings()` so existing call sites don't need updating.
   - `tests/test_reports_api.py::_add_time_entry` — constructed `TechnicianTimeEntry` directly via the ORM (needed for report tests requiring specific historical clock-in/out times, unreachable through the real clock-in route). Fixed to resolve `shop_id` via `resolve_shop_id_for_owner`.
   - `scripts/seed_estimate_approval_fixture.py` — used by real e2e tests to avoid a billable OpenAI research call, directly constructs `Customer`/`Vehicle`/`Estimate`/`EstimateRevision`. Fixed to resolve `shop_id` once and pass it through all four.
   - `tests/e2e/test_reports_csv_export.py` — directly constructs `Technician`/`TechnicianTimeEntry` to seed report data. Fixed.
   - `tests/e2e/seed.py` — directly constructs `Estimate`/`EstimateRevision` (the same "avoid a billable OpenAI call" pattern). Fixed by mirroring the already-loaded `Customer`'s `shop_id`.
   - A repo-wide AST sweep (same methodology as Phase 1's threadpool fix) confirmed **zero remaining direct constructions** of any of the 30 target model classes anywhere in `app/`, `tests/`, or `scripts/` missing `shop_id`, after these fixes.
6. `tests/e2e/test_shop_id_not_null.py` (new) — 2 tests against real Postgres: the migration succeeds and sets NOT NULL when no orphans exist; the migration refuses to proceed (exact error message asserted, DB left at the prior revision, column still nullable) when an orphan row exists.
7. `tests/e2e/test_shop_id_backfill.py` — one existing test (`test_backfill_sets_shop_id_from_owner_membership_and_leaves_orphans_null`) updated to migrate only to `024_backfill_shop_id` instead of `head`, since it deliberately creates an orphan row to prove migration 024's own "leave unmatched NULL" behavior — migrating further to 025 would just reproduce that migration's (correct, expected) refusal rather than testing anything new.
8. `docs/context/KNOWN_ISSUES.md`, `docs/context/GOAL_EVIDENCE_MATRIX.md`, `docs/context/RELEASE_CHECKLIST.md` — updated with this slice's scope and findings.

Business-table *read*/query-scoping is still untouched — no store module filters by `shop_id` for authorization anywhere. That cutover remains a separate, later, higher-risk slice.

## Verified baseline

- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check .` / `ruff check .` → clean.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright` → 0 errors, 0 warnings.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` → **402 passed**, 2 pre-existing unrelated skips.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/e2e/` → **16 passed** (14 pre-existing + 2 new), no leftover containers.
- Migration 025 rehearsed live against a real, isolated scratch Postgres 16 container: succeeded cleanly on a clean/backfilled DB (confirmed 34 tables NOT NULL: 30 new + 4 pre-existing `shop_*`); downgrade reverted exactly 30 tables back to nullable (the 4 `shop_*` tables' own `shop_id` stayed NOT NULL, unaffected); re-seeded an orphan row and confirmed the migration refused with the exact expected error message, left `alembic_version` at 024 (not partially advanced), and left the column nullable — genuinely atomic, not a partial-failure risk.
- `scripts/check_shop_id_orphans.py` verified directly: reports "safe to proceed" (exit 0) on a clean DB, correctly detects and reports a seeded orphan row (exit 1) with the exact expected message.

## Evidence

- All verification above was run directly in this session against a real, isolated Postgres container — not assumed from a prior claim.
- The 5 gaps this slice found are not hypothetical: each was a real `sqlalchemy.exc.IntegrityError`/`NotNullViolation` that appeared when the fast and e2e suites were run after adding the NOT NULL constraint, not a finding from static inspection — the test suite going from 10 failures → 0 failures after each fix, tracked one at a time, is itself the evidence.

## Unverified

- This diff is not yet committed, pushed, PR'd, or reviewed. That's the immediate next step: commit, push to a new branch, open a PR, get independent + security review, fix any real findings, then merge once green.
- No independent or security review has run on this diff yet.

## Unrelated preexisting changes

- Untracked stray `optimusOS/` directory at the repo root — predates every session on record, not part of any commit, still present, still "leave alone" per every prior handoff.

## Blockers and risks

- None blocking. No real credentials, billing, or production/staging deployment were touched this increment.

## Exact next task

Commit this diff, push, open a PR, get independent + security review, fix any real findings, then merge once green. After that, Phase 3's schema/data work is essentially complete for `shop_id` — the next slice is the higher-risk one: cutting store-module *read* queries over from `owner_user_id`/`effective_owner_id` to `shop_id`, table by table, each with its own cross-shop isolation tests before merge, per `/goal`'s explicit "every shop query needs isolation tests" rule and its "any cross-shop leak blocks release" stop condition. This is a good point to consider whether that cutover should be one slice per table (very small, very safe, very slow) or grouped by domain (customers+vehicles together, work-order-adjacent tables together, etc.) — recommend grouping by domain to keep the slice count manageable while still keeping each PR reviewable.

## Carried over from prior sessions — not touched by this session

- Ask the owner to re-test the three staging bugs reported after the Phase 5.5 deploy (notifications reachable via mobile nav + desktop sidebar; estimate "Refresh status" button; Square tab visible in both nav surfaces) — still the oldest open follow-up, not yet re-confirmed.
- Payment-schedule installment percentage split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`).
- The staging droplet is still behind current `main`. Catching it up is a deploy action requiring explicit current-turn approval and real credentials this session does not have.
- Square: email-TLD and phone-format validation gaps found during an earlier sandbox smoke test are non-blocking, no fix requested yet. Staging still has no Square credentials configured.
- `ShopMembership` rows aren't created for technicians added via the normal `create_technician_record` flow after migration 022 — deliberately deferred to Phase 5 (see `docs/context/KNOWN_ISSUES.md`).
- The `ondelete="CASCADE"` choice on all 30 `shop_id` FKs (financial/audit tables included) is an open data-retention policy decision, not yet resolved — revisit before any shop-deletion/offboarding feature ships (see `docs/context/KNOWN_ISSUES.md`).
