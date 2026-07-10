# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-10.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/PLANS.md`, `docs/context/KNOWN_ISSUES.md`, `git status`/`git log`, full local gate runs on 2026-07-10, live checks against the local compose stack and `https://staging.optimus-os.com` (post-redeploy).

## Identity

- Updated UTC: 2026-07-10T05:15Z
- Agent: Claude (implementer this session; independent review by a separate read-only reviewer agent completed in-session; Codex/owner review of the committed diff still recommended)
- Branch: `agent/claude/notify-history-square`, HEAD `ac7b4d2`, pushed to `origin/agent/claude/notify-history-square`. Not yet merged into `ops/staging` or `main` — owner decides PR vs. merge.
- Worktree: primary (`/home/dejake/optimus-server`); untracked stray `optimusOS/` clone still present (owner's accidental clone — leave alone)

## Active task — Phase 5.5 four-feature slice: IMPLEMENTED AND COMMITTED

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
- **Committed and pushed 2026-07-10** with owner approval: `3228597` (feature slice) + `ac7b4d2` (docs) on `origin/agent/claude/notify-history-square`. Codex/owner review of the committed diff is the recommended next pass.

## Staging droplet redeploy — DONE 2026-07-10

Discovery during the deploy: `ops/staging` had already been merged into `main` via PR #11 (`b38a811`, GitHub-side, between sessions) and the remote branch deleted — same pattern as PR #10. So the droplet only needed a fast-forward pull of `main`, no branch switch.

Executed (owner explicitly authorized direct SSH execution after initially asking to review the plan first):
1. `git fetch origin` on droplet → `git pull --ff-only origin main`: clean fast-forward `36b861b..b38a811`, no conflicts. Droplet now has the invoice-button fix (`1139499`), the optimusctl `COMPOSE_OVERRIDE_FILE` fix (`7d665c8`), and the ruff-drift cleanup (`15481c6`).
2. Added `COMPOSE_OVERRIDE_FILE=ops/docker-compose.staging.yml` to the droplet's `.env` (single-line append, not present before).
3. `scripts/optimusctl.sh update` → rebuilt backend/worker images, restarted. `status` confirmed frontend at `0.0.0.0:80->80/tcp` (the override took effect — no regression to `127.0.0.1:5173`). `health` returned 200 locally on the droplet.
4. **Verified externally from this machine**: `https://staging.optimus-os.com/static/app.js?cb=<ts>` contains `selectionVersion` (5 occurrences) — the invoice-button fix is confirmed live through Cloudflare. `/health` 200, HSTS header present.

Note: the Phase 5.5 branch (`agent/claude/notify-history-square`, migration head `010`) is NOT yet on the droplet — only `main` up to `15481c6` is deployed. When Phase 5.5 merges, the droplet needs `alembic upgrade head` as an explicit step (head will move `009`→`010`).

**Remaining from the original droplet checklist**: owner still needs to do one full browser login on staging and the manual invoice-button repro click-through (open a work order → "Open invoice" → confirm the three buttons stay enabled). Not yet confirmed this session — purely a browser action, not something an agent can perform.

## Next steps

1. **Codex/owner review** of the committed Phase 5.5 diff (`3228597`, `ac7b4d2`) — recommended second-pass review before merging into `ops/staging`/`main`.
2. **Owner: decide PR vs. direct merge** for `agent/claude/notify-history-square` → `ops/staging`.
3. **Owner: Square sandbox smoke test** — still blocked on credentials. Create a Square developer sandbox (developer.squareup.com), put the sandbox access token + location id in the local `.env` only (never chat/commits), restart backend (`--force-recreate` — env is fixed at container start), then push a real issued invoice via the UI button and confirm the email/pay-link on Square's sandbox dashboard. `.env` currently has neither `SQUARE_ACCESS_TOKEN` nor `SQUARE_LOCATION_ID` set (checked by presence only, not value).
4. **Owner: staging browser checks** — full login with the rotated password, and the invoice-button manual repro (see above).
5. When Phase 5.5 deploys to the droplet: remember the `alembic upgrade head` step (009→010) is not automatic.

## Verified baseline (carried forward, still true)

- Staging live and now on the latest `main`: `https://staging.optimus-os.com/health` + `/ready` 200; **HSTS confirmed live**; **staging owner password rotation confirmed by owner**; **invoice-button fix confirmed live** (all closed this session or 2026-07-09).
- PR #10 and PR #11 both merged `ops/staging`→`main` on GitHub between sessions with the remote branch deleted each time — if a future session pushes another `ops/staging`, expect the same pattern.

## Blockers and risks

- Phase 5.5 diff is committed/pushed but not yet merged into `ops/staging`/`main` or deployed anywhere — still needs the review/merge decision above.
- Local alembic head (`010`) is ahead of the droplet (`009`) until Phase 5.5 merges and deploys — track the `alembic upgrade head` step when that happens.
- Carried over: payment-schedule installment split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`); no rate limiter on `POST /api/estimates` (pre-existing, documented in Slice 1).

## Exact next task

Get Codex or owner review of the committed Phase 5.5 diff, then decide how it merges into `ops/staging`. Separately, whenever the owner is ready: Square sandbox credentials for the smoke test, and the two remaining staging browser checks (full login, invoice-button repro).
