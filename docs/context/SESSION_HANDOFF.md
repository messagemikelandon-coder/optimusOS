# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-19.

## Identity

- Agent/task owner: Claude, `/goal` Phase 7 (subscription billing).
- Synced `main`: `e36a75a18e16dc65bec8b1cb4746ef0a30b715d0` (PR #63, Phase 6 workflow-gap tracking).
- Active worktree: `/home/dejake/optimus-server/.claude/worktrees/phase7-subscription-billing`.
- Active branch/HEAD: `agent/claude/goal-phase7-subscription-billing`, uncommitted on top of `e36a75a`; not yet pushed/PR'd/merged.

## Active task

`/goal` Phase 7, subscription billing: charging a *Shop* to use OptimusOS itself, a new domain distinct from `app/square_store.py`'s existing customer-invoice integration. The owner supplied the real spec before implementation began (not invented): Square Subscriptions (sandbox), three seat-based tiers (Solo $49/mo/1 seat, Team $99/mo/up to 5 seats, Shop $199/mo/unlimited seats), a 14-day free trial for new self-service signups, and a grace-period-then-suspend policy on payment failure. Fully implemented, gated, tested, and locally verified this session; publication (commit/push/PR/merge) requires the owner's current-turn approval per this repo's git-coordination rules.

Out of scope for this slice: platform support impersonation/admin, observability infrastructure, full Shop export/deletion, feature flags, onboarding checklist, feedback intake, real card-capture UI (see Unverified), real live/production Square calls, staging/production deployment, and irreversible real-data actions.

## Verified baseline

- `ruff format --check .` (174 files) and `ruff check .` — clean.
- `pyright` — 0 errors, 0 warnings.
- `node --check app/static/app.js` — clean.
- Fast suite: **471 passed, 2 skipped** (456 prior + 14 new subscription-billing tests + 1 new landing-page markup test).
- Full e2e suite (real Postgres + real Chromium): **34 passed** (30 prior + 4 new: 1 migration round-trip incl. pre-existing-shop grandfathering, 1 real-concurrency seat-limit test, 2 real-browser tests; `test_signup_ui.py`'s existing browser test was updated in place to drive through the new choose-plan step, not added as a new file).
- `git diff --check` — clean. `python3 scripts/check_ai_handoff.py` — OK.
- Independent correctness review (`optimus-reviewer`) and independent security review (`optimus-security-reviewer`): both run this session; two real findings from each, all fixed and re-verified (see Evidence).

## Evidence

- New migration `031_subscription_billing` adds `shop_subscriptions` (tier/billing_status/seat_limit/trial/period/grace-period timestamps/Square ids), `shop_id`-scoped with `ON DELETE CASCADE`, chained off `030_workflow_gaps`. Reuses the existing `shop_events` table for the audit trail rather than adding a redundant per-domain events table, since `ShopEvent` already documents itself as the shop-level administrative-action log. Backfills every pre-existing `Shop` row (the real pilot install included) onto a grandfathered, already-active, unlimited-seat subscription with no trial timer and no Square objects — proven against a real Postgres container that a shop existing *before* this migration gets exactly that (`tests/e2e/test_subscription_billing_migration.py`), and that the migration is cleanly reversible.
- `app/subscription_store.py` is the store module: tier/pricing table (`SUBSCRIPTION_TIERS`), trial start (self-service signup only) vs. grandfathering (bootstrap/synthetic/pre-existing shops), payment-method/subscribe/tier-change/cancel/refresh-from-Square, and `count_active_technician_seats`. Every function scopes through `effective_shop_id(db, auth)`, the same Phase 3 pattern every other business table uses.
- **Derived-status architecture, not a background job**: `app/auth.py::sync_shop_access_status` recomputes whether a shop's access should be suspended from `ShopSubscription`'s real timestamps (trial_ends_at/grace_period_ends_at/current_period_end) on every business-route request, matching this codebase's existing convention for invoice status/balance (physical `Shop.status` column is only a best-effort cache, corrected — with a `ShopEvent` logged — whenever the derived state actually changes). This means a trial or grace period expiring is enforced immediately without needing a cron/worker job to notice it first; proven directly (`tests/test_subscription_billing_api.py`).
- Enforcement is threaded into the existing role-gate dependencies (`require_owner_context`/`require_owner_or_technician_context` in `app/auth.py`, both now take a `db` parameter) rather than touching all ~50 existing business routes individually. A new `require_billing_context` dependency (owner/manager role-gated but deliberately *not* suspension-gated) protects the 6 new `/api/billing/*` routes, so a suspended shop can still view its billing status and add a payment method to restore access — proven by a new `_BILLING_ROUTES` bucket in `tests/test_role_isolation.py`'s existing static route-gating audit.
- Seat-limit enforcement lives in `app/technician_store.py::create_technician` (one seat = one non-archived `Technician` profile), row-locking the subscription first so two concurrent creates at exactly the limit cannot both pass — proven under real concurrent Postgres writers (`tests/e2e/test_subscription_billing_concurrency.py`, asserting exactly one of two racing creates succeeds).
- `app/services/square.py` gained `SquareSubscriptionClient` (Customers/Cards/Subscriptions REST calls), sharing a new `_SquareClient` base class with the existing `SquareInvoiceClient` rather than duplicating the connection/request plumbing a second time.
- New owner/manager-only "Billing" panel in the System bay (`app/static/index.html`/`app.js`): tier/trial/grace-period/seat-usage summary, a plan selector with Subscribe/Change-plan/Cancel actions, and an "Add sandbox test card" button using Square's documented sandbox success nonce (`cnon:card-nonce-ok`) — a disclosed stand-in for a real card-capture form (see Unverified).
- **Owner follow-up request, same session**: public pricing on the marketing landing page, and letting a prospective owner subscribe before reaching the dashboard.
  - Landing page (`app/static/index.html`): a "Pricing" button in the header nav (anchors to a new `#pricing` section), and a new pricing section with all three tiers as cards, each linking to `/signup?tier=<solo|team|shop>` (a real, pre-existing top-level route — no new backend route needed).
  - Post-signup onboarding: a new "Choose your plan" view (`#view-choose-plan`) is shown once, right after email verification succeeds, before the dashboard — reusing the already-built, already-reviewed `/api/billing/*` endpoints (no new backend surface). The chosen landing-page tier is pre-highlighted via `sessionStorage`. Skipping keeps the existing 14-day trial running unchanged; the flow is a one-time client-side redirect (`sessionStorage`-flagged at signup, consumed on first post-verification navigation), not a new server-side onboarding-state field, so it never resurfaces on a later login.
  - New markup regression test (`tests/test_official_ui.py::test_marketing_landing_page_has_a_pricing_section_and_nav_link`) and an updated real-browser signup test (`tests/e2e/test_signup_ui.py`) that now drives through the choose-plan step before reaching the dashboard.
- `docs/context/GOAL_EVIDENCE_MATRIX.md`'s subscription-billing row updated from "Not started/Absent" to "Complete locally, publication pending."
- **Two real findings fixed this session, both from independent review, re-verified after fixing:**
  - **(Security, Medium) Seat-limit bypass via invitation acceptance.** `app/account_security_store.py::accept_invitation` is a second code path that can create a brand-new `Technician` row (the other being `technician_store.create_technician`), and it had no seat-limit check at all — a shop on the Solo (1-seat) tier could accept unlimited technician invitations and staff far past what it pays for. Fixed by extracting the existing row-locked check into a public `app/technician_store.py::enforce_technician_seat_limit` and calling it from `accept_invitation`'s new-Technician branch too, rolling back and rejecting with the same generic invitation error on conflict. New regression test: `tests/test_subscription_billing_api.py::test_technician_invitation_acceptance_is_seat_limit_gated`.
  - **(Correctness, Medium) Cancellation never actually preserved access through the paid period.** `cancel_subscription`'s "access continues to period end" comment was aspirational — nothing ever captured Square's real `charged_through_date` into `current_period_end`, so it was always `None` at cancel time and every cancellation suspended immediately, identical to a never-paid trial. Fixed by parsing `charged_through_date` (a bare `YYYY-MM-DD` string) from Square's subscribe/change-tier/refresh responses into `current_period_start`/`current_period_end`. New regression test: `tests/test_subscription_billing_api.py::test_subscribe_captures_period_end_so_cancellation_grants_a_real_grace_window`.
  - Also hardened (Low/Medium, correctness): `app/auth.py::_is_subscription_access_suspended`'s `trialing`/`past_due` branches now fail closed (suspended) rather than open if their expiry timestamp is ever unexpectedly unset — not reachable through any current code path, but a latent trap the reviewer flagged.
  - Both reviews' remaining checks (cross-shop isolation, the `require_owner_context`/`require_owner_or_technician_context` suspension-gate change, `require_billing_context`'s narrower scope, Square secret/id leakage, the seat-limit row-lock's actual concurrency safety, SQL injection, migration reversibility, sandbox-nonce labeling) all returned PASS with no further findings.

## Unverified

- **No real Square sandbox account is configured in this environment** (`.env.example`'s `SQUARE_*` keys are blank, same as the pre-existing invoice integration). Every Square-calling code path was verified against a stub client (unit tests) and confirmed to fail cleanly with a clear 503 when unconfigured (real-browser test). No real Square API call has ever been made by this slice.
- No real card-capture UI exists. Square Subscriptions' card-on-file step normally needs client-side tokenization via Square's Web Payments SDK (a `js.squareup.com` script), which this app's `script-src 'self'` CSP does not currently permit — embedding it is a real architecture decision (CSP exception or a different capture flow) that was not made unilaterally. The sandbox test-nonce button is a disclosed stand-in, not production-ready.
- No real Square Catalog subscription plans/plan-variations exist yet — `SQUARE_SOLO_PLAN_VARIATION_ID`/`SQUARE_TEAM_PLAN_VARIATION_ID`/`SQUARE_SHOP_PLAN_VARIATION_ID` ship blank in `.env.example`; each must be created once in the Square sandbox dashboard before that tier is subscribable. Blank means `subscribe()`/`change_tier()` reject with a clear error, not a broken Square call.
- No webhook receiver exists for real-time Square subscription events — this mirrors the existing invoice integration's own pattern (a pull-based `/api/billing/refresh` route, not a push webhook). A future slice could add one if real-time updates matter more than periodic/manual refresh.
- No proration on mid-cycle tier changes; the new price applies at the next billing cycle (Square's own default behavior for a plan-variation swap).

## Unrelated preexisting changes

- Root worktree `/home/dejake/optimus-server` remains on `main` with the pre-existing untracked nested `optimusOS/` clone; not touched.
- Older worktrees (`account-lifecycle`, `tenant-boundary`, `synthetic-accounts`, `release-process`, `workflow-gaps`) remain separate and were not edited by this session. Note: a Codex process was observed still running inside `workflow-gaps` mid-session (that branch's own PR #63 was already merged and its remote branch deleted earlier this session) — not investigated further since it is a different worktree this session does not own.
- Fixed one now-stale assertion in a **pre-existing** Phase 3 test (`tests/e2e/test_shop_tenant_migration_backfill.py`) that asserted an exact, single-item `shop_events` list for a migrated shop — that test upgrades to `head`, so migration 031's own grandfathering event legitimately extends the list. Updated the expected list rather than weakening the assertion.

## Blockers and risks

- No engineering blocker. Local implementation, runtime proof, gates, and independent review are all complete; only publication remains.
- Real payment-provider setup (Square sandbox account, Catalog plan variations, and eventually a production-ready card-capture UI) remains an owner/infrastructure decision, same category as this repo's existing email-provider and staging-deployment gaps.

## Exact next task

1. Review the full diff one more time, then get the owner's explicit approval before committing/pushing/opening a PR for this slice.
2. Wait for CI, merge, and sync `main`.
3. Cut the next isolated Phase 8 branch/worktree (support administration domain, per the evidence matrix) and continue the `/goal` roadmap.
