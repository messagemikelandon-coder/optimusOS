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
- `main` HEAD: `62b48a4` (PR #56, Phase 3 slices 5+6 — `shop_id` NOT NULL constraint) as of this doc being written; PR #57 (Phase 4 slice 1) is reviewed and ready to merge, see below.
- Current worktree/branch: `agent/claude/goal-phase4-shop-signup`, branched from `origin/main` at `62b48a4`. Commit `fb9cea9` (initial slice) and a follow-up commit `688d45e` (review-finding fixes) are both pushed to PR #57.

## Active task

This session is executing the `/goal` multi-shop-pilot roadmap (17 phases; see `docs/context/GOAL_EVIDENCE_MATRIX.md`). Phases 0-3 are merged (Phase 3's `shop_id` schema/data work is complete: nullable → backfilled → auto-populated on create → NOT NULL; business-table *read*/query-scoping onto `shop_id` remains a separate, later, higher-risk slice, deferred since it only matters once a shop can have multiple owners — which this Phase 4 work introduces the *possibility* of, but doesn't yet exploit). This increment is **Phase 4 slice 1: self-service shop signup (backend only)**.

Work in this increment:

1. `alembic/versions/026_user_account_email.py` (new) — adds nullable `email`/`email_normalized` to `user_accounts`, with a partial unique index (`WHERE email_normalized IS NOT NULL`) so pre-existing accounts with no email never collide with each other, but any two real emails must be distinct platform-wide.
2. `app/db_models.py` — `UserAccount` gets the matching `email`/`email_normalized` columns + the partial unique index.
3. `app/models.py` — new `ShopSignupRequest` (business_name, owner_display_name, username, email, password).
4. `app/shop_store.py` — `signup_shop_owner(db, settings, payload) -> UserAccount`: validates username/email uniqueness explicitly (not left to a raw `IntegrityError`), hashes the password, creates the owner account, then calls `create_shop_for_new_owner` (now extended with optional `display_name`/`created_via` parameters so a new shop gets the *signup's own* business name, never the hardcoded `settings.business_name` "Landon Motor Works" default).
5. `app/main.py` — `POST /api/signup`: rate-limited via a new dedicated `enforce_signup_rate_limit`/`get_signup_rate_limiter` (own `max_signup_attempts_per_minute` setting, mirroring the existing login-limiter pattern exactly), creates a real session and sets the cookie on success (auto-login, matching `/api/auth/login`'s exact flow), logs a new `SIGNUP_SUCCEEDED`/`SIGNUP_FAILED` security event pair.
6. `tests/test_role_isolation.py` — added `("POST", "/api/signup")` to the not-role-gated allowlist (it's public by definition, same category as `/api/auth/login`).
7. `tests/conftest.py` — the autouse rate-limiter-reset fixture now also resets the new `main._signup_rate_limiter`/`_signup_rate_limiter_redis_url` globals (otherwise the very first test using the default `max_signup_attempts_per_minute=5` would exhaust it against later, unrelated tests in the same process).
8. `tests/test_signup_api.py` (new) — 8 tests: successful signup + shop creation + auto-login, case-insensitive email normalization, duplicate username/email rejection (case-insensitive), invalid email format, weak password rejection, rate limiting, and full cross-shop isolation between two signed-up shops (customers, list, and direct-object-access all correctly isolated).
9. `tests/e2e/test_signup_e2e.py` (new) — one test hitting the real live API (no browser/Playwright, since there's no frontend signup form yet) proving the full chain: signup → real session cookie → authenticated `/api/auth/me` → authenticated `/api/customers` create, all against real Postgres.

**Real, previously-undiscovered bug found and fixed in this same slice** (found while writing the weak-password test, verified before assuming it was real): `NonBlank = Field(min_length=8, ...)` — the exact pattern already used for `AuthLoginRequest.password` and `TechnicianProvisionLoginRequest.password` — never actually enforced an 8-character minimum anywhere in this app. Pydantic merges `Field()`'s constraints with `NonBlank`'s own baked-in `StringConstraints(min_length=1)` into one metadata list, and the later item silently wins, so only `min_length=1` was ever enforced. Confirmed directly: constructing `AuthLoginRequest` with username `owner` and a 5-character credential value validated with no error before the fix. Fixed with a new dedicated type (`Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=256)]`, no separate `Field()` call so there's no second conflicting constraint source), applied to all 3 affected fields. `strip_whitespace=True` was deliberately preserved exactly as before (confirmed via a direct test), so this does not change what any existing account's stored credential hash was computed from — it only starts correctly rejecting genuinely-too-short values at request validation, which was always the documented intent (see `.env.example`'s own guidance to set a long value for the owner bootstrap credential).

Not in this slice (explicitly deferred): frontend signup form/UI, "resumable setup guidance" checklist (Phase 12's own item), email verification (Phase 5/6), password reset (Phase 5/6).

**Independent + security review (PR #57) findings, fixed before merge** (full detail in `docs/context/KNOWN_ISSUES.md`'s Phase 4 slice 1 review entry):

1. High/correctness — `signup_shop_owner`'s uniqueness pre-check was a plain `SELECT` with no protection against the database's own unique-constraint firing at `db.flush()` for a genuine concurrent-signup race (this codebase's own `app/technician_store.py::provision_technician_login` already had the correct `try/except IntegrityError` pattern for the identical race; this slice hadn't mirrored it). Fixed; proven via revert-and-recheck (without the fix, the new regression test fails with a raw unhandled `IntegrityError`) plus `tests/test_signup_api.py::test_signup_converts_flush_time_race_to_a_clean_conflict`.
2. Medium-High/security — distinct 409 messages for a username conflict vs. an email conflict let an unauthenticated caller enumerate registered accounts on this platform's first public account-creation endpoint. Fixed: both now return one identical generic message; the specific reason is logged to the `SIGNUP_FAILED` security event only, via a new `ShopSignupConflictError.reason` attribute, never in the HTTP response. Regression test: `tests/test_signup_api.py::test_signup_conflict_message_does_not_reveal_which_field_collided`.
3. Low/correctness coverage gap — added direct weak-password regression tests for the two pre-existing fields the `Password`-type fix (from this same slice) silently repaired (`AuthLoginRequest.password`, `TechnicianProvisionLoginRequest.password`) — previously only the new `ShopSignupRequest.password` field had one.

Accepted as documented follow-ups, not fixed in this slice (per the security reviewer's own recommendation that only finding #2 blocks merge): the signup rate limiter's IP-only keying is weak against IP rotation for a resource-creating public endpoint (revisit alongside Phase 5/6 email verification); `business_name`/`owner_display_name` have no HTML-escaping yet, not currently exploitable since no render path uses `shop.display_name` yet (flag for whichever future slice first does).

## Verified baseline

- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check .` / `ruff check .` → clean (post-review-fix state).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright` → 0 errors, 0 warnings.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` → all passed, exit 0 (410 + 3 new review-fix regression tests = 413; 2 pre-existing unrelated skips).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/e2e/` → **18 passed** (17 prior + no new e2e test this round), no leftover containers.
- Migration 026 rehearsed live against a real, isolated scratch Postgres 16 container: upgrade succeeds, columns/partial-unique-index confirmed present; downgrade cleanly drops both columns and the index; re-upgrade succeeds.
- The `NonBlank`/`Password` bug fix was verified both ways directly: confirmed the bug existed (an `AuthLoginRequest` built with a 5-character credential value validated with no error) before touching any code, then confirmed the fix (same call now raises `ValidationError`) and confirmed whitespace-stripping behavior is unchanged (a padded value still strips to the same value it always did). Now also has direct regression tests on both pre-existing affected fields (see review-findings section above).
- The TOCTOU race fix (finding #1 above) was verified via revert-and-recheck: temporarily removed the `try/except IntegrityError` around `db.flush()`, confirmed `test_signup_converts_flush_time_race_to_a_clean_conflict` then fails with a raw unhandled `sqlalchemy.exc.IntegrityError` (not a clean 409), restored the fix, confirmed the test passes again.

## Evidence

- All verification above was run directly in this session — not assumed from a prior claim.
- Grepped the entire test suite for any password shorter than 8 characters used in an actual login attempt (not just a `Settings(...)` construction that bypasses Pydantic validation entirely, like `bootstrap_owner_account` does) — found none, so the `Password` fix broke nothing in this repo's own test suite.
- Grepped `tests/test_signup_api.py` and confirmed no test asserts the old, distinct conflict-message wording, so making both messages generic broke nothing already committed.

## Unverified

- Whether any *real* deployment's actual owner or technician password is shorter than 8 characters is unknown and unknowable from this session (no access to real credentials) — flagged in `docs/context/KNOWN_ISSUES.md` as a disclosed risk of the fix, not verified against real production data.

## Unrelated preexisting changes

- Untracked stray `optimusOS/` directory at the repo root — predates every session on record, not part of any commit, still present, still "leave alone" per every prior handoff.

## Blockers and risks

- None blocking. No real credentials, billing, or production/staging deployment were touched this increment. The one disclosed risk (a real account with a <8-character password would newly be rejected at login) is a correctness fix, not a new vulnerability, but worth the owner's awareness before this reaches any real deployment with real accounts.

## Exact next task

Commit the review-fix changes (fixes for findings #1-#3 above, on branch `agent/claude/goal-phase4-shop-signup`), push, and re-request review only if warranted by finding severity (the High/Medium-High findings were substantial — lean toward at least a light re-review confirming the fixes are sound rather than merging on documentation alone, unlike the Low/Medium PR #56 precedent). Once green, merge PR #57 (`gh pr merge 57 --squash`) and delete the remote branch. After that, continue Phase 4 with a frontend signup form (reusing the existing landing-page/login-page visual style already established), and/or move to the "resumable setup guidance" checklist (Phase 12) or start Phase 5 (account lifecycle/security: email verification, password reset, sessions, invitations) — Phase 5's password-reset work in particular now has a real `email` column to send a reset link to, which didn't exist before this slice.

## Carried over from prior sessions — not touched by this session

- Ask the owner to re-test the three staging bugs reported after the Phase 5.5 deploy (notifications reachable via mobile nav + desktop sidebar; estimate "Refresh status" button; Square tab visible in both nav surfaces) — still the oldest open follow-up, not yet re-confirmed.
- Payment-schedule installment percentage split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`).
- The staging droplet is still behind current `main`. Catching it up is a deploy action requiring explicit current-turn approval and real credentials this session does not have.
- Square: email-TLD and phone-format validation gaps found during an earlier sandbox smoke test are non-blocking, no fix requested yet. Staging still has no Square credentials configured.
- `ShopMembership` rows aren't created for technicians added via the normal `create_technician_record` flow after migration 022 — deliberately deferred to Phase 5 (see `docs/context/KNOWN_ISSUES.md`).
- The `ondelete="CASCADE"` choice on all 30 `shop_id` FKs (financial/audit tables included) is an open data-retention policy decision, not yet resolved — revisit before any shop-deletion/offboarding feature ships (see `docs/context/KNOWN_ISSUES.md`).
- `app/shop_store.py::resolve_shop_id`/`resolve_shop_id_for_owner` returning `None` could surface as an unhandled `IntegrityError` at ~15 call sites now that `shop_id` is NOT NULL — not currently reachable, tracked as an accepted follow-up (see `docs/context/KNOWN_ISSUES.md`).
