# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-08.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/PLANS.md`, `docs/context/KNOWN_ISSUES.md`, `git status`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`, `docker compose exec -T backend alembic current`, `docker compose exec -T backend alembic heads`, non-billable direct-DB/API proof commands run locally on 2026-07-08.

## Identity

- Updated UTC: 2026-07-08T22:40Z
- Agent: Claude
- Branch: `feat/payment-tracking`
- HEAD: `85e9bce9cf8575ce3b2d7b44fb1458bde9682749` (`feat: add invoice generation`) — Phase 3 is complete in the working tree, uncommitted
- Worktree: primary (`/home/dejake/optimus-server`)

## Active task

- Goal: implement **Phase 3 — Payment Tracking** from the committed Phase 2 invoice baseline.
- Status: **Done, pending commit approval.** Schema, derived balances/status, API, UI, 16-case test list, full gates, Docker/Alembic round-trip, independent review, security review, and non-billable live proof are all satisfied in the working tree; nothing has been committed or pushed yet.
- Out of scope (owner-confirmed 2026-07-08): any Square or other external payment processor integration, any live/billable payment API call, and any change to Square/external scheduling or the existing Work Order status lifecycle — Square is deferred to its own future phase. Also out of scope per the original plan: change-order routing into `waiting_for_approval`, an invoice-level `void` route, editing/deleting a recorded payment, and any background scheduler for overdue transitions.

## Verified baseline

- Migration head in the rebuilt backend container: `009_payments`.
- Files changed: `app/db_models.py`, `app/models.py`, `app/invoice_store.py`, `app/main.py`, `app/static/index.html`, `app/static/app.js`; new `app/payment_store.py`, `alembic/versions/009_payments.py`, `tests/test_payments_api.py` (16 cases). Confirmed via empty `git diff app/work_order_store.py` that the WorkOrder status enum/`TRANSITIONS` table is untouched — only its `PAYMENT_PLAN_OPTIONS` constant is imported read-only.
- API surface added: `POST /api/invoices/{id}/payments`, `POST /api/invoices/{id}/payments/{payment_id}/void`; `GET /api/invoices`/`GET /api/invoices/{id}` extended with `total_paid`, `balance_due`, `is_overdue`, `payments[]`, `schedule[]`.
- Design: append-only `invoice_payments` (voids insert a negative reversal row, DB `UniqueConstraint` blocks double-void), `payment_schedules` generated once on issue. Status/`total_paid`/`balance_due`/`is_overdue` always derived server-side, recomputed fresh at read, never client-supplied. Decimal money math throughout; float only at the response boundary. Payment-schedule percentage split is an owner-confirmed placeholder (even default split) pending real business-rule confirmation — see `docs/context/BUSINESS_RULES.md`.
- Accepted deviations from the original plan (flagged by independent review, not blocking): `record_payment`/`void_payment` live in a new `app/payment_store.py` module rather than inside `invoice_store.py`; `InvoicePaymentCreate.amount` has an added `le=1_000_000` upper bound.
- Prior baseline: Phase 1 committed/pushed to `origin/feat/work-orders` (`f6dd75d`); Phase 2 committed/pushed to `origin/feat/invoices` (`85e9bce`). Full history and fix-by-fix detail for those phases is in `git log` and `docs/context/KNOWN_ISSUES.md`, not repeated here.

## Evidence

- Gates (2026-07-08): `ruff format` clean on the 7 files this slice touched; `ruff check .` all passed; `pyright` 0 errors; `pytest -q` 165 passed; `node --check app/static/app.js` OK.
- Docker/Alembic (2026-07-08): `docker compose build backend worker` + `up -d backend worker frontend`; `alembic heads`/`current` → `009_payments (head)`; rollback rehearsed clean (`alembic downgrade 008_invoices` → `alembic upgrade head` → back at `009_payments (head)`).
- Independent review (2026-07-08): no correctness bugs, no regressions, all 16 test cases present, cross-user isolation confirmed on both new routes.
- Security review (2026-07-08): one medium finding — overpayment check not race-safe under concurrent requests to the same invoice — fixed same-day with a `SELECT ... FOR UPDATE` row lock in `app/payment_store.py::record_payment`; full gates re-ran green after the fix. No other findings.
- Non-billable live proof (2026-07-08), fixture-seeded estimate, no OpenAI call, owner session constructed directly against the real DB without ever reading/printing `.env`: two-month-plan estimate → work order → blocked premature scheduling (prereqs unmet) → deposit payment recorded → `deposit_received` flipped by the payment itself → invoice issued with a 3-row schedule summing exactly to `invoice_total` in Decimal → `partially_paid` → overpayment rejected → balance paid in full → `paid`, balance `0` → deposit voided → recomputed to `partially_paid`, balance `186.31`, `deposit_received` still `true` → double-void rejected. Restarted `backend`/`worker`: identical state after restart. Second synthetic owner got `404` on `GET`/record-payment/void-payment for the first owner's invoice. Result summary: `estimate_id=71`, `work_order_id=8`, `invoice_id=6`, `owner_user_id=12`.

## Unverified

- No browser/Playwright UI click-through of the new record-payment/void-payment controls was performed — verification was at the API/store level (direct route-function calls against the real Docker/Postgres stack), matching this repo's non-billable proof pattern but not a full UI E2E pass. The frontend JS/HTML changes were checked with `node --check` and manual code review only.
- No live/billable OpenAI call was made (correctly out of scope — the estimate was fixture-seeded).

## Unrelated preexisting changes

- Repo-wide `ruff format --check .` flags 4 files (`app/work_order_store.py`, `tests/test_invoices_api.py`, `tests/test_official_ui.py`, `tests/test_work_orders_api.py`) as needing reformatting. Confirmed via `git stash` that this drift predates this session and is unrelated to the Phase 3 diff — not fixed here to keep the diff scoped.
- `origin/main` advanced one merge commit (PR #6) during this session, but it only folded in commits already present on this branch (work-orders + invoices) — no rebase was needed.

## Blockers and risks

- Phase 3 is fully verified but **not committed or pushed** — needs explicit commit/push approval before this branch can close out or Phase 4 can start from a clean baseline.
- Payment-schedule installment percentage split is a known placeholder, not a defect — real business-rule confirmation is still open in `docs/context/BUSINESS_RULES.md`.

## Exact next task

Get explicit commit/push approval for the completed Phase 3 slice on `feat/payment-tracking`; then begin Phase 4 — Full Local MVP Hardening per `docs/context/PLANS.md`. Square (payments and/or scheduling) is explicitly deferred to its own future phase — do not fold it into Phase 4.
