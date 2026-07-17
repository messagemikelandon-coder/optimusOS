# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-17.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/KNOWN_ISSUES.md`, `docs/context/GOAL_EVIDENCE_MATRIX.md`, `git log`/`git status`, `gh pr view`, `pytest -q`.

## Identity

- Updated UTC: 2026-07-17.
- Agent: Claude.
- `main` HEAD: `8114a15` (PR #51, Phase 2 — CI backup/restore/rollback rehearsal).
- Current worktree/branch: `agent/claude/goal-phase3-shop-slice1-models`, branched from `origin/main` at `8114a15`. Uncommitted diff described below, not yet committed/pushed/PR'd as of this doc being written.

## Active task

This session is executing the `/goal` multi-shop-pilot roadmap (17 phases; see `docs/context/GOAL_EVIDENCE_MATRIX.md` for the full requirement-by-requirement reconciliation). Phases 0-2 are merged to `main`. This increment is **Phase 3 slice 1: Shop/tenant model — create the tables and backfill only** (the first of several staged slices; business tables still scope by `owner_user_id`, not `shop_id` — that's a later slice, per `/goal`'s own instruction not to do a blind destructive replacement in one diff).

Uncommitted work on this branch:

1. `app/db_models.py` — new `Shop`, `ShopSettings`, `ShopMembership`, `ShopInvitation`, `ShopEvent` SQLAlchemy models.
2. `app/models.py` — matching `ShopRole`/`ShopStatus` `StrEnum`s and `ShopRead`/`ShopSettingsRead`/`ShopMembershipRead`/`ShopInvitationRead`/`ShopEventRead` Pydantic models.
3. `alembic/versions/022_shop_tenant_model.py` — creates the 5 tables, then backfills: one real "Landon Motor Works" shop per pre-existing non-synthetic owner (from `app/config.py::Settings` — real business name/labor rate/fees, nothing fabricated; every field this codebase has no real value for — address, phone, email, hours, terms text, branding — stays NULL), an owner `ShopMembership`, and a `ShopMembership` for each of that owner's non-synthetic technicians.
4. `app/shop_store.py` (new) — `get_current_shop`/`get_current_shop_settings`/`list_current_shop_memberships` (read-only; no routes wired to `main.py` yet, deliberately out of this slice's scope), plus `create_shop_for_new_owner`.
5. `app/auth.py::bootstrap_owner_account` — now also calls `create_shop_for_new_owner`. **This was a real gap I found and fixed, not part of the original plan**: a fresh install runs `alembic upgrade head` before any owner exists, so migration 022's own backfill (which only covers owners that already existed at migration time) never fires for a fresh install — without this fix, a brand-new deployment would end up with an owner but no shop at all. Uses a deferred (in-function) import of `app.shop_store` in `app/auth.py` to avoid a circular import (`app.shop_store` imports `AuthContext`/`effective_owner_id` from `app.auth`).
6. `tests/test_shop_store.py` (new) — 9 tests: bootstrap creates a shop/settings/owner-membership with real config values and no fabricated fields, technician membership resolves to the owner's shop, an account with no membership raises `ShopNotFoundError`, `create_shop_for_new_owner`'s own fabrication boundary, and the 3 new DB-level constraints (membership uniqueness, membership role CHECK, shop status CHECK).
7. `docs/context/KNOWN_ISSUES.md` — new Confirmed Open Issue: `ShopMembership` rows aren't created for technicians added via the normal `create_technician_record` flow after this migration (only by the migration backfill and `create_shop_for_new_owner`) — deliberately deferred to Phase 5, no production impact today since no business table reads `shop_id` yet.
8. `docs/context/GOAL_EVIDENCE_MATRIX.md` — Part C rows for the Shop model and cross-shop isolation updated from Absent to Complete/Partial with the verification evidence below.

## Verified baseline

- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check .` → clean (136 files).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` → clean.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright` → 0 errors, 0 warnings.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` → **399 passed**, 2 pre-existing unrelated skips.
- Migration rehearsed live against a real, isolated scratch Postgres 16 container (separate compose project/volumes/ports from the other checkout's already-running stack, which was left untouched and reconfirmed via `docker ps` afterward):
  - Upgrade 021 → 022 against a simulated **existing deployment** (real owner + real technician + a synthetic technician inserted directly via SQL): backfill created exactly one shop ("Landon Motor Works", real config values, all unknown fields NULL), one owner membership, one technician membership — the synthetic technician was correctly excluded.
  - Downgrade 022 → 021: all 5 new tables dropped cleanly, `user_accounts` untouched.
  - Upgrade to head again against a **fresh install** (zero owners at migration time, so zero shops from the backfill, confirmed), then ran `python -m app.bootstrap_owner`: created the owner **and** a shop/settings/membership via the new `create_shop_for_new_owner` path — confirms the fresh-install gap fix works.
  - Before the image was rebuilt with the latest source, the same command against DB head 021 (pre-022) correctly raised `UndefinedTable: relation "shops" does not exist` and rolled back the owner insert too (no partial row committed) — confirms the migration is a real, load-bearing prerequisite and the transaction is atomic.
- Scratch `.env`, compose override file, and the scratch backend image were all deleted after verification; no e2e (`tests/e2e/`) run this increment — no new HTTP routes were added in this slice for e2e to exercise.

## Evidence

- All of the above verification was run directly in this session (not assumed from a prior claim) — commands and outputs described above are reproducible from a clean checkout of this branch.
- The fresh-install Shop-creation gap was found by actually reasoning through call order (`optimusctl.sh migrate` runs before `bootstrap-owner`), then proven live rather than left as a hypothesis.

## Unverified

- **This diff is not yet committed, pushed, PR'd, or reviewed.** That's the immediate next step.
- No independent or security review has run on this diff yet — due before merge per this repo's standing discipline, especially since it touches account-bootstrap logic (`app/auth.py`) and adds a new backfill migration with real data-mutation semantics.

## Unrelated preexisting changes

- Untracked stray `optimusOS/` directory at the repo root — predates every session on record, not part of any commit, still present, still "leave alone" per every prior handoff.

## Blockers and risks

- None blocking. No real credentials, billing, or production/staging deployment were touched this increment.

## Exact next task

Get independent + security review on this diff, fix any real findings, then commit/push/open a PR/merge per the standing `/goal` authorization (own feature branch, non-force push, merge when green and reviewed). After that, continue Phase 3 with the next staged slice: wiring `shop_id` (nullable first) onto business tables is explicitly **not** part of slice 1 and should be its own separate, reviewable PR, per `/goal`'s own staged-migration instruction. Also queue, for Phase 5 (not this slice): folding `ShopMembership` create/deactivate into the technician creation/deletion lifecycle so `list_current_shop_memberships` stays accurate over time (see `docs/context/KNOWN_ISSUES.md`).

## Carried over from prior sessions — not touched by this session

- Ask the owner to re-test the three staging bugs reported after the Phase 5.5 deploy (notifications reachable via mobile nav + desktop sidebar; estimate "Refresh status" button; Square tab visible in both nav surfaces) — still the oldest open follow-up, not yet re-confirmed.
- Payment-schedule installment percentage split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`).
- The staging droplet is still behind current `main`. Catching it up is a deploy action requiring explicit current-turn approval and real credentials this session does not have.
- Square: email-TLD and phone-format validation gaps found during an earlier sandbox smoke test are non-blocking, no fix requested yet. Staging still has no Square credentials configured.
