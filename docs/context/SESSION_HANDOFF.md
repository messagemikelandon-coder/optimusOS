# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-10.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/PLANS.md`, `docs/context/KNOWN_ISSUES.md`, `git status`/`git log`, full local gate runs on 2026-07-10, a real Square sandbox smoke test, live checks against the local compose stack and `https://staging.optimus-os.com` (post-deploy).

## Identity

- Updated UTC: 2026-07-10T06:30Z
- Agent: Claude (implementer; independent review by a separate read-only reviewer agent completed in-session)
- Branch: `main`, HEAD `147bf97` (local and `origin/main` both current). `agent/claude/notify-history-square` merged into `main` via PR #12 + #13 on GitHub and deleted (same pattern as the prior `ops/staging` PRs). `ops/staging` currently does not exist as a remote branch.
- Worktree: primary (`/home/dejake/optimus-server`); untracked stray `optimusOS/` clone still present (owner's accidental clone — leave alone)

## Active task — Phase 5.5 four-feature slice: SHIPPED (built, reviewed, merged, deployed, smoke-tested)

Owner goal (2026-07-09 /goal): every estimate saved with approved/declined tracking + automatic customer history; notification on estimate approve/decline; a Notifications tab covering estimate/invoice/work-order status; Square integration for invoicing/scheduled payments (sandbox-only this phase). Owner confirmed: customer-first estimate flow, in-app notifications + badge, Square Invoices API sandbox-first.

Originally handed to Codex; the owner's /goal stop-condition required same-session delivery, so Claude implemented it 2026-07-10 on `agent/claude/notify-history-square` (one-agent-one-branch preserved; Codex never started).

### What was built (all verified by the gates below)

**Slice 1 — transient `POST /api/estimate` retired.** The UI already posted to persisted `POST /api/estimates` (customer+vehicle required), so the orphaned billable, nothing-saved route was deleted from `app/main.py`; its three tests in `tests/test_api.py` were ported to the persisted route (auth-required path string; API-key-503 via `create_estimate_record`; structured 504 upstream-error with a real customer+vehicle and monkeypatched orchestrator). Rate limiting was NOT added to `/api/estimates` (never had one; documented gap, not a regression).

**Slice 2 — customer history.** New `app/customer_history_store.py` (`get_customer_history`: owner-scoped 404 via `get_customer_model`, three direct queries filtered owner+customer, `ORDER BY updated_at DESC LIMIT`, COUNT totals; invoice rows use `invoice_store._payment_summary(now_utc())` so status/balance/overdue are read-time truth). New models `CustomerHistory*` in `app/models.py`; route `GET /api/customers/{id}/history?limit=` in `app/main.py`; `#customer-history` panel with three sub-lists in `index.html` + `loadCustomerHistory()`/`renderCustomerHistory()` wired into `selectCustomer` in `app.js` (click-throughs reuse `openEstimateRecord`/`selectWorkOrder`/`selectInvoice`). Tests: `tests/test_customer_history_api.py` (6) + isolation-sweep line + official-ui ids.

**Slice 3 — notifications.** Migration `alembic/versions/010_notifications_square.py` (down_revision `009_payments`): `notifications` table (owner FK CASCADE; polymorphic entity_type/entity_id, no entity FK; event CHECK; title/body; mutable `read_at` null=unread — the one documented deviation from append-only; two owner indexes) **plus** the Slice-4 `invoices.square_invoice_id/square_status/square_payment_url` columns (single-migration rule). `Notification` model in `db_models.py`. New leaf module `app/notification_store.py`: `record_notification` (db.add only, rides the caller's transaction), `list_notifications` (paginated, unread filter, `unread_count` in every response), `mark_notification_read` (owner-scoped 404), `mark_all_notifications_read`. In-transaction hooks at all seven producers: `send_estimate_for_approval`, `approve_estimate` + `decline_estimate` (owner derived from `estimate.owner_user_id` — public token path has no AuthContext; the expired early-commit path deliberately does not notify), `transition_work_order_status` (staged before the COMPLETED branch so it rides/rolls back with `ensure_draft_invoice_for_work_order`'s internal commit), `issue_invoice`, `record_payment` (body notes deposit flip), `void_payment`. Routes: `GET /api/notifications`, `POST /api/notifications/{id}/read`, `POST /api/notifications/read-all`. Settings: `notifications_default_page_size`/`notifications_max_page_size`. Frontend: nav tab with `#nav-notifications-badge` unread pill, notifications view (list, unread-only filter, mark-all, pager, refresh), 60s badge poll beside the health poll, badge refresh on login, cleared on logout. Tests: `tests/test_notifications_api.py` (8: full-chain sequence, customer-token approval notifies owner, unread/mark-read flow, isolation, idempotent no-op adds no row, failed COMPLETED transition rolls the notification back, pagination + max-page-size 422) + idempotency-audit extension + official-ui ids.

**Slice 4 — Square Invoices, sandbox-only.** Config: `square_access_token (repr=False)`, `square_environment Literal["sandbox","production"]="sandbox"`, `square_location_id`, `square_timeout_seconds`, property `square_configured` — true ONLY with token+location AND environment=="sandbox" (production structurally unreachable this phase); `.env.example` section added. `app/services/square.py`: `SquareInvoiceClient(settings, client=None)` (injectable stub seam; pinned `Square-Version: 2025-05-21`; sandbox base URL; `SquareApiError` carries status+codes, never the token), six calls with deterministic idempotency keys (`{invoice_number}:{step}`): search-customer-by-email → create-customer → create-order (ONE aggregate line item; cents via `_money()` Decimal, never `int(float*100)`) → create-invoice (payment_requests from `payment_schedules`: ≤1 row → BALANCE; 2+ rows → DEPOSIT (first row, fixed amount) + BALANCE (final due date), middle installments collapsed into the description — Square INSTALLMENT needs a paid tier) → publish (Square emails the customer the pay link) → get. `app/square_store.py`: `push_invoice_to_square` (draft/void→422, already-pushed→409, missing snapshot email→422; square columns persisted ONLY after the full sequence succeeds), `refresh_square_invoice` (not-pushed→422). Routes `POST /api/invoices/{id}/square/push|refresh` (503 unless `square_configured`; SquareApiError→502 sanitized), `/health` gains `square_configured`+`square_environment`, `InvoiceRead` gains the three square fields. **Square never writes the local ledger** — owner records money manually via the existing payment form (`method_label` e.g. "Square"). Frontend: "Send with Square" (confirm() gate — money-adjacent action) + "Refresh Square status" buttons on invoice detail, Square status + pay-link rows; hidden entirely unless health reports `square_configured`. Tests: `tests/test_square_api.py` (12, all via `StubSquareClient` — zero network: unconfigured/production 503s, happy path new+existing customer, Decimal cents equality, draft 422, no-email 422, re-push 409, publish-failure persists nothing, refresh, ledger untouched with local status still unpaid while Square says PAID, cross-user 404s, `repr(Settings)` never contains the token).

### Evidence (2026-07-10)

- `ruff format app tests scripts alembic` + `ruff check` clean (scoped — `.` would recurse into stray `optimusOS/`).
- `pyright`: 0 errors. `node --check app/static/app.js` clean.
- `pytest`: **200 passed** (174 baseline + 26 new).
- Alembic on the real compose Postgres: `upgrade head` (009→010) → `downgrade 009_payments` → `upgrade head` all clean; `alembic current` = `010_notifications_square (head)`.
- Backend/worker images rebuilt; live curl proofs: new routes 401 unauthenticated (auth gate ahead of the Square config gate), `/health` shows `square_configured: false` + `square_environment: sandbox` on the unconfigured local stack, served `app.js`/`index.html` contain the new tab/panels, real Postgres has the `notifications` table and the three `square_*` invoice columns.
- Independent review (separate read-only reviewer agent, 2026-07-10): **no CRITICAL findings.** Three IMPORTANT findings, all addressed before handoff:
  1. Unclosed `httpx.Client` per Square push/refresh request → fixed: `SquareInvoiceClient.close()` (closes only self-created clients, never injected stubs) + `finally: client.close()` in both routes + a `stub.closed` regression assertion.
  2. Pre-existing commit-boundary gap in `ensure_draft_invoice_for_work_order`'s early-return/IntegrityError branches (the new notification inherits it in a concurrent double-completion race) → accepted as documented pre-existing risk, now recorded in `docs/context/KNOWN_ISSUES.md`.
  3. Coverage note: only the injected-stub Square path is unit-tested; the real httpx path and the `asyncio.to_thread` routes under a live ASGI request are exercised only by the owner sandbox smoke test — carried as an explicit gap, not a defect.
  - Reviewer's suggested hardening also applied: DB-level unique index `uq_invoices_square_invoice_id` added to model + migration (NULLs don't collide; one Square invoice can never map to two local invoices).
  - All gates re-run green after the fixes.
- **Merged into `main`**: PR #12 (through `ac7b4d2`) then PR #13 (final docs commit `5b1d1e2`) on GitHub — `origin/main` HEAD `147bf97` has the full feature set. Remote feature branch deleted after merge (established pattern for this repo).

## Square sandbox smoke test — DONE 2026-07-10, real network, no stubs

Owner created real Square sandbox credentials and set them in the local `.env`; backend recreated to pick them up (`docker compose up -d --force-recreate backend worker`) — `/health` confirmed `square_configured: true`.

Built the full chain via direct store-function calls inside the backend container (non-billable — no OpenAI call, using `scripts/seed_estimate_approval_fixture.py`'s pattern for a synthetic estimate, same non-billable-proof convention as earlier phases): customer → estimate → sent for approval → approved via the public token path → work order → walked to `completed` (auto-created draft invoice) → issued → pushed to **the real Square sandbox API** (no test stub).

Result: real Square invoice created (`inv:0-ChBfLZwZtNkWasJjYtJacNpvEJgN`), status `UNPAID`, real pay link returned (`https://app.squareupsandbox.com/pay-invoice/...`). Refresh re-fetched from Square and updated local status correctly. **Local ledger stayed completely untouched** — `total_paid: 0`, `balance_due` unchanged, zero payment rows, confirming the "Square never writes the local ledger" design guarantee under a real (not mocked) Square response.

Three real findings from the live test:
1. **Fixed by owner**: `SQUARE_LOCATION_ID` had been set to the Square **Application ID** by mistake (both are shown on similar-looking dashboard pages) — corrected to the real sandbox location id, found via a live `GET /v2/locations` call with the owner's own token.
2. **Non-blocking**: Square's live validator rejects `.test`-TLD emails (RFC-2606-reserved, syntactically valid, but Square's own validator refuses them) — this is our own fixture-seeding convention (`scripts/seed_estimate_approval_fixture.py` uses `@example.test`), not a real-customer risk; a real customer's real email won't hit this.
3. **Non-blocking**: Square requires E.164 phone format (`+1...`); our customer records store free-text phone (e.g. `555-0112`). If a real customer's phone isn't E.164, the push fails with a generic 502 rather than a clear "fix this phone number" message. No money-safety or security issue — the push simply doesn't persist anything, exactly as designed. Worth a future small hardening pass (phone normalization + a friendlier error) but not requested/blocking.

## Staging droplet deploy — DONE 2026-07-10 (both the invoice-button fix AND the Phase 5.5 slice)

Deployed in two passes as `main` advanced on GitHub:
1. First pass: droplet fast-forwarded `36b861b`→`b38a811` (invoice-button fix `1139499`, optimusctl `COMPOSE_OVERRIDE_FILE` fix `7d665c8`, drift cleanup `15481c6`). `COMPOSE_OVERRIDE_FILE=ops/docker-compose.staging.yml` added to droplet `.env` (wasn't present before). `scripts/optimusctl.sh update` rebuilt/restarted; `status` confirmed frontend held at `0.0.0.0:80->80/tcp`. Verified externally: `selectionVersion` present in the served `app.js` through Cloudflare.
2. Second pass (after Phase 5.5 merged to `main`): droplet fast-forwarded again to `147bf97`. `scripts/optimusctl.sh update` rebuilt/restarted (port binding still held). `scripts/optimusctl.sh migrate` applied `alembic upgrade head` — confirmed `alembic current` = `010_notifications_square (head)` on the droplet's real database.

**Verified externally from this machine (not just the droplet) after both passes**: `https://staging.optimus-os.com/health` now returns `square_configured`/`square_environment` fields; the served `app.js` contains all three new-feature markers (`loadNotifications`, `customer-history`, `square/push`); `index.html` serves the Notifications tab; `/ready` healthy. **Staging's own `square_configured` is `false`** — its `.env` has no Square credentials (only the local dev stack does); Square is proven working against the real sandbox only from local, not yet from staging. Adding staging Square credentials is a small separate step if the owner wants it.

Both SSH deploy passes were executed directly by Claude over root SSH after the owner explicitly authorized it mid-session (the original plan had said "owner runs droplet commands, Claude prepares them" — a permission-boundary question from the owner was clarified and the owner then explicitly said to proceed).

**Still outstanding, browser-only, not agent-performable**: one full login on staging with the rotated password, and the manual invoice-button repro click-through (open a work order → "Open invoice" → confirm the three buttons stay enabled).

## Verified baseline (carried forward, still true)

- Staging live on latest `main` (`147bf97`) with all Phase 5.5 features: `https://staging.optimus-os.com/health` + `/ready` 200; **HSTS confirmed live**; **staging owner password rotation confirmed by owner**; **invoice-button fix confirmed live**; **customer history / notifications / Square (config-gated, unconfigured on staging) all confirmed live**.
- PR #10, #11, #12, #13 all merged a working branch into `main` on GitHub between/during sessions with the remote branch deleted each time — expect the same pattern for any future feature branch.

## Blockers and risks

- Carried over: payment-schedule installment split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`); no rate limiter on `POST /api/estimates` (pre-existing, documented in Slice 1); pre-existing work-order-completion race documented in `KNOWN_ISSUES.md`.
- Email-TLD and phone-format Square validation gaps (see smoke test section) — non-blocking, no fix requested yet.
- Staging does not have Square credentials configured — only local dev has been proven against the real Square sandbox.

## Exact next task

No blocking work remains from this session. Optional follow-ups if the owner wants them: staging browser checks (login + invoice-button repro), Square credentials on staging, or the phone/email validation hardening noted above.
