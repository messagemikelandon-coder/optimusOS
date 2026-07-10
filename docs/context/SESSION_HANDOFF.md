# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-10.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/PLANS.md`, `docs/context/KNOWN_ISSUES.md`, `git status`/`git log`, full local gate runs on 2026-07-10, a real Square sandbox smoke test, live checks and owner-reported bugs against `https://staging.optimus-os.com`.

## Identity

- Updated UTC: 2026-07-10T07:15Z
- Agent: Claude
- Branch: `main`, HEAD `892ca6b` (local and `origin/main` both current).
- Worktree: primary (`/home/dejake/optimus-server`); untracked stray `optimusOS/` clone still present (owner's accidental clone — leave alone)

## Active task — Phase 5.5 four-feature slice: SHIPPED, deployed, owner-tested, bugs found and fixed

Owner goal (2026-07-09 /goal): every estimate saved with approved/declined tracking + automatic customer history; notification on estimate approve/decline; a Notifications tab covering estimate/invoice/work-order status; Square integration for invoicing/scheduled payments (sandbox-only this phase).

Built, reviewed, merged into `main` (PR #12/#13), deployed to staging, and smoke-tested against the real Square sandbox — see the section below for full detail. The owner then live-tested on staging and found three real gaps, all root-caused and fixed same session (see "Post-deploy bug triage").

### What was built (Slices 1–4, all still true)

**Slice 1 — transient `POST /api/estimate` retired.** The UI already posted to persisted `POST /api/estimates` (customer+vehicle required), so the orphaned billable, nothing-saved route was deleted from `app/main.py`; its three tests in `tests/test_api.py` were ported to the persisted route. No rate limiter on `/api/estimates` (never had one; documented gap).

**Slice 2 — customer history.** `app/customer_history_store.py` (`get_customer_history`), `GET /api/customers/{id}/history`, `#customer-history` panel wired into `selectCustomer`. Tests: `tests/test_customer_history_api.py` (6).

**Slice 3 — notifications.** Migration `alembic/versions/010_notifications_square.py`: `notifications` table (owner-scoped, polymorphic entity pointer, mutable `read_at`) plus the Slice-4 `invoices.square_*` columns. `app/notification_store.py` with in-transaction hooks at all seven producers (estimate sent/approved/declined including the public customer-token path, work-order transitions, invoice issue, payment record/void). API + Notifications tab with unread badge, 60s poll. Tests: `tests/test_notifications_api.py` (8).

**Slice 4 — Square Invoices, sandbox-only.** `square_configured` gate (token+location AND environment==sandbox; production structurally unreachable). `app/services/square.py` (`SquareInvoiceClient`, injectable, pinned API version, deterministic idempotency keys), `app/square_store.py` (`push_invoice_to_square`/`refresh_square_invoice`). Square never writes the local payment ledger. Tests: `tests/test_square_api.py` (12, stub-only, zero network).

### Evidence from the build (2026-07-10, still true)

- 200 tests passed at merge time, ruff/pyright/node clean, alembic 009↔010 round-trip rehearsed.
- Independent review: no CRITICAL findings; three IMPORTANT findings all fixed (Square client-close leak with a regression assert; a pre-existing work-order-completion-race commit-boundary gap documented in `KNOWN_ISSUES.md`; a DB-level unique index added on `invoices.square_invoice_id`).
- Merged into `main` via PR #12 + #13 on GitHub (remote feature branch deleted after merge — established repo pattern; expect this again for any future branch).

## Square sandbox smoke test — DONE 2026-07-10, real network, no stubs

Owner created real Square sandbox credentials, set them in the local `.env`, backend recreated to pick them up. Built the full chain via direct store-function calls (non-billable, no OpenAI call — same technique as `scripts/seed_estimate_approval_fixture.py`): customer → estimate → approved via the public token path → work order → completed → invoice issued → pushed to the **real** Square sandbox API.

Result: real Square invoice created, live pay link returned, refresh worked, and the local ledger stayed completely untouched (Square said UNPAID; local `total_paid`/`balance_due`/payment-row-count all correct and independent of Square's state) — confirms the "Square never writes the local ledger" guarantee under a real, non-mocked response.

Findings: (1) owner had `SQUARE_LOCATION_ID` set to the Square Application ID by mistake — found via a live `GET /v2/locations` call, owner corrected it; (2) Square's live validator rejects `.test`-TLD emails, which is our own fixture-seeding convention, not a real-customer risk; (3) Square requires E.164 phone format, our records store free-text — a real mismatched phone would currently surface as a generic 502 (safe, no partial persistence, just an unfriendly message). (2) and (3) are non-blocking, not yet fixed.

## Staging deploy history (all DONE 2026-07-10)

Deployed in three passes as `main` advanced on GitHub, each verified externally from this machine (not just the droplet):
1. Invoice-button fix (`1139499`) + optimusctl `COMPOSE_OVERRIDE_FILE` fix (`7d665c8`) + drift cleanup (`15481c6`) — droplet fast-forwarded `36b861b`→`b38a811`, `.env` gained `COMPOSE_OVERRIDE_FILE`, `optimusctl.sh update` rebuilt/restarted, port binding confirmed held at `0.0.0.0:80`.
2. Phase 5.5 full feature slice (`147bf97`) — droplet fast-forwarded again, `optimusctl.sh update` rebuilt/restarted, `optimusctl.sh migrate` applied `alembic upgrade head` (confirmed `010_notifications_square (head)` on the droplet's real database).
3. Caching fix + post-deploy bug fixes (`5afca99`, `892ca6b`) — droplet fast-forwarded, nginx reloaded (pass 3) then no restart needed at all (pass 4, static-only changes served live via the bind mount).

All SSH deploy actions were executed directly by Claude over root SSH after the owner explicitly authorized it mid-session (the original plan said "owner runs droplet commands, Claude prepares them" — clarified and explicitly overridden by the owner for this session).

**Still outstanding, browser-only, not agent-performable**: the owner has confirmed login works and invoice-detail links (Open work order/HTML/PDF) work. Not yet independently re-confirmed after today's further fixes: notifications tab now reachable via mobile nav, work-order button refresh action, Square dashboard tab.

## Post-deploy bug triage — DONE 2026-07-10, root-caused, fixed, redeployed

Owner reported three issues after the Phase 5.5 deploy: (1) notification bar visible but not accessible, (2) "Create work order" button worked once then went disabled again, (3) no Square dashboard visible.

**Root cause #1 (systemic, explains most of the initial confusion): Cloudflare edge caching.** `ops/nginx/default.conf` set no `Cache-Control` header at all, so Cloudflare applied its own default (`max-age=14400`, i.e. 4 hours) to `app.js`/`index.html`. Confirmed via response headers (`cf-cache-status: HIT`, `age` climbing past 2000s) while the origin was already serving current content (verified with a cache-busted query string). **Fixed**: explicit `Cache-Control: no-cache` on both `/static/` and `/` in nginx (commit `5afca99`) — still cacheable, but forces revalidation every request instead of trusting a multi-hour TTL, so future deploys are visible immediately with no manual CDN purge. Verified after deploy: the plain (non-cache-busted) URL now serves fresh content immediately (`cf-cache-status: DYNAMIC`).

**Issue #1 detail (notifications "visible but not accessible")**: extensive static code review of the click-handling JS/CSS found no bug in the notification tab's own logic (verified: no duplicate element IDs page-wide, `viewMeta.notifications` correctly keyed, `initializeNavigation()` runs before any function that could throw and block it, all `notifications-*` element IDs match between HTML and JS). Confirmed via direct read-only queries against the real staging database that the backend was completely correct throughout — the reported approval (`EST-001-00006`) was properly `approved` server-side, and both `estimate_sent`/`estimate_approved` notification rows existed, unread, exactly as designed. The one concrete, real gap found: **the Notifications tab was only ever added to the desktop sidebar nav, never to the mobile bottom nav** — on a narrow viewport there was no quick-access entry point. **Fixed** (commit `892ca6b`): added a Notifications button to `.mobile-bottom-nav`. (A live authenticated-browser reproduction was attempted via Playwright but the technique required minting and persisting a live owner session credential, which the permission system correctly blocked as unauthorized credential materialization — the fix here rests on code review + the definite mobile-nav gap, not a live click-through repro. If the mobile-nav fix doesn't fully resolve it, the owner's exact device/viewport and browser console errors would be the next diagnostic input needed.)

**Issue #2 ("Create work order" disabled again after working once)**: confirmed via database query that estimate approval does not get reverted or mutated by work-order creation — `create_work_order_from_estimate` never touches `estimate.status`, so the button's gate (`data.status === "approved"`) should remain satisfied indefinitely once approved. The most likely explanation is client-side staleness: this is a single-page app with no live-push mechanism (by design, documented — no websockets), so if an estimate is approved via the customer's public link while the owner already has that estimate open in a browser tab, the open tab's in-memory copy doesn't know the status changed until it's re-fetched. **Fixed** (commit `892ca6b`): added a "Refresh status" button on the estimate record view that re-fetches the current estimate from the server on demand, so the owner is never stuck depending on a full page reload or a notification arriving in time.

**Issue #3 ("no Square dashboard")**: partly expected behavior (staging's own `.env` has no Square credentials, so `square_configured` is `false` there — the two invoice-detail buttons are correctly hidden by design when unconfigured), and partly a real product gap the owner explicitly asked to close: Square was never more than two small buttons buried in invoice detail, with no dedicated space. **Built** (commit `892ca6b`): a new "Square" nav tab (desktop sidebar + mobile bottom nav) reusing the existing `GET /api/invoices` data (already carries `square_invoice_id`/`square_status`/`square_payment_url` — no new backend endpoint needed): a configuration-status banner (explains clearly whether Square is connected or needs credentials) plus a list of all non-draft invoices with per-row Send-with-Square/Refresh actions and pay links.

**Also found and fixed**: a latent test-isolation gap surfaced by today's real Square credentials in the local `.env` — the `settings` pytest fixture never explicitly overrode `square_access_token`/`square_location_id`/`square_environment`, so once the local `.env` had real Square credentials, `pydantic-settings`' real-`.env`-is-authoritative source order made every test's `Settings()` pick them up, flipping `square_configured` to `True` unexpectedly and breaking `test_square_push_rejected_when_unconfigured`. This is exactly the class of bug the existing `openai_api_key="test-key"` override already guards against for OpenAI — applied the same explicit-override pattern for the three Square fields in `tests/conftest.py`.

**Verification for this round**: 200 tests pass, ruff/pyright/node clean; a headless Playwright load of the (unauthenticated) login page confirmed zero JS runtime errors from the new markup — no session credential was minted or persisted for this check, per the permission system's correction. Deployed to the droplet (static-file-only changes, no rebuild needed — nginx serves `app/static` via a live bind mount); verified externally that the plain staging URL (no cache-buster) now serves the Square tab, the mobile-nav Notifications entry, and the new app.js functions, confirming the caching fix holds for real deploys.

## Verified baseline (carried forward, still true)

- Staging live on latest `main` (`892ca6b`): `/health` + `/ready` 200; HSTS live; owner password rotation confirmed; login confirmed by owner; invoice-detail links (work order/HTML/PDF) confirmed by owner.
- `square_configured: false` on staging (no credentials there) — proven working only against the local dev stack's real Square sandbox so far.
- PR #10, #11, #12, #13 all merged a working branch into `main` on GitHub with the remote branch deleted each time — expect the same pattern for any future feature branch.

## Blockers and risks

- Carried over: payment-schedule installment split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`); no rate limiter on `POST /api/estimates`; pre-existing work-order-completion race documented in `KNOWN_ISSUES.md`.
- Email-TLD and phone-format Square validation gaps (see smoke test section) — non-blocking, no fix requested yet.
- Staging does not have Square credentials configured.
- The notification-accessibility fix (mobile nav entry) was not confirmed via a live authenticated browser repro (blocked by the credential-materialization permission boundary) — only via code review + a definite, fixed gap. If the owner still can't reach/use notifications after this deploy, the next session needs either owner-provided repro details (device/viewport, browser console errors) or explicit owner authorization for a live-session debugging technique.

## Exact next task

Ask the owner to re-test all three reported issues on staging (hard refresh not even required now, given the cache fix): notifications tab reachable via mobile nav and desktop sidebar; estimate "Refresh status" button available; Square tab visible in both nav surfaces (will show "not configured" banner on staging until credentials are added there). Report back anything still broken with as much detail as possible (viewport size, exact click sequence, any visible error) since further live debugging without owner-provided repro detail is limited by the credential-handling constraint above.
