# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-10.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/PLANS.md`, `docs/context/KNOWN_ISSUES.md`, `git status`, full local gate runs on 2026-07-10, live checks against the local compose stack and `https://staging.optimus-os.com`.

## Identity

- Updated UTC: 2026-07-10T04:00Z
- Agent: Claude (implementer this session; independent review by a separate read-only reviewer agent completed in-session; Codex/owner review of the committed diff still recommended)
- Branch: `agent/claude/notify-history-square`, created from `ops/staging` (`15481c6`); **all Phase 5.5 work is uncommitted in this worktree**, awaiting owner commit approval
- Worktree: primary (`/home/dejake/optimus-server`); untracked stray `optimusOS/` clone still present (owner's accidental clone — leave alone; contains 4 formatting-dirty files from an earlier accidental `ruff format .`; owner can `git checkout -- .` inside it or delete it)

## Active task — Phase 5.5 four-feature slice: IMPLEMENTED, uncommitted

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
  - All gates re-run green after the fixes. Codex/owner review of the committed diff still recommended as the second pass.

## Next steps (exact)

1. **Owner: approve commit.** Suggested shape: one commit per slice (or a single squashed feature commit — owner's call) on `agent/claude/notify-history-square`, then push and open a PR into `ops/staging` (or straight merge — owner's call).
2. **Owner: Square sandbox smoke test** (optional until wanted): create a Square developer sandbox (developer.squareup.com), put the sandbox access token + location id in the local `.env` only (never chat/commits), restart backend (`--force-recreate` — env is fixed at container start), then push a real issued invoice via the UI button and confirm the email/pay-link on Square's sandbox dashboard.
3. **Owner action still pending from Phase 5**: droplet redeploy one-liners (unchanged, below), then post-deploy verification.

## Owner action items (pending)

1. **Droplet deploy** (invoice fix + optimusctl fix are NOT yet on the droplet — it still runs `36b861b`). One line at a time (console mangles multi-line pastes):
   `cd /opt/optimus-server && git fetch origin`
   `git checkout ops/staging`
   `git pull --ff-only origin ops/staging`
   `grep COMPOSE_OVERRIDE_FILE .env` → if empty: `echo 'COMPOSE_OVERRIDE_FILE=ops/docker-compose.staging.yml' >> .env`
   `scripts/optimusctl.sh update` then `status` (frontend MUST show `0.0.0.0:80->80/tcp`) then `health`
   Then an agent verifies `selectionVersion` in `https://staging.optimus-os.com/static/app.js` (cache-buster; Cloudflare may cache) and the owner does the browser repro check + one full login.
2. **Square sandbox credentials** for the smoke test (see Next steps 2).

## Verified baseline (carried forward, still true)

- Staging live: `https://staging.optimus-os.com/health` + `/ready` 200; **HSTS confirmed live**; **staging owner password rotation confirmed by owner** (both closed 2026-07-09).
- `scripts/optimusctl.sh` honors `COMPOSE_OVERRIDE_FILE` (commit `7d665c8`); format-drift files fixed (`15481c6`); both pushed to `origin/ops/staging`.
- PR #10 discovery: remote `main` (`a1b84ff`) already contains invoice fix `1139499`; old remote feature branches deleted; `origin/ops/staging` recreated by the 2026-07-09 push.

## Blockers and risks

- Commit/push/PR/merge all need explicit owner approval (repo rule) — the whole Phase 5.5 diff is sitting uncommitted until then.
- Local alembic head (010) is now ahead of the droplet (009) — the droplet deploy above only takes `ops/staging`, which does NOT include this branch; when Phase 5.5 merges and deploys, run `alembic upgrade head` on the droplet as an explicit step.
- Carried over: payment-schedule installment split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`); no rate limiter on `POST /api/estimates` (pre-existing, documented in Slice 1).

## Exact next task

Get owner approval to commit the Phase 5.5 diff (per-slice or squashed), push `agent/claude/notify-history-square`, and decide PR-vs-merge into `ops/staging`. Then resume the pending droplet redeploy (Owner action item 1).
