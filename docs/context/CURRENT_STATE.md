# Current State

Purpose: concise operational snapshot of the verified current repository state.
Information owner: repository maintainers and the current Codex session author.
Read when: before every task, together with `SESSION_HANDOFF.md`.
Update when: the branch, working status, live stack status, migrations, or quality-gate results change.
Last verified date: 2026-07-10.
Relevant sources: `git status --short --branch`, `git rev-parse HEAD`, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`, `node --check app/static/app.js`, `docker compose config -q`, `docker compose build backend worker`, `docker compose up -d backend worker frontend`, `docker compose exec -T backend alembic heads`, `docker compose exec -T backend alembic upgrade head`, `docker compose exec -T backend alembic current`, non-billable Playwright/API proof commands run from the local shell.

## Operational Snapshot

- Active development phase: **Phase 5.5 is merged to `main` and deployed to staging (see "Post-deploy bug triage" history below and `SESSION_HANDOFF.md`). Branch `agent/claude/landing-page-redesign` now carries two IMPLEMENTED, UNCOMMITTED slices: (1) the Landing Page Redesign, and (2) an Overview dashboard + Approval Queue rebuild that replaces the old "Shop intelligence online" hero. All gates green (210 tests, ruff, pyright, node syntax) but pending independent review sign-off and owner commit approval — see the "Landing Page Redesign" and "Overview Dashboard & Approval Queue" sections below.**
- Current branch: `agent/claude/landing-page-redesign` (created off `main` at `ab8ed98`). The primary worktree (`/home/dejake/optimus-server`) was clean on `main` before this branch was created; nothing from Phase 5.5 was uncommitted at that point.
- Git working state: Phase 2 merged via PR #6 (`8be1dba`); Phase 3 via PR #7 (`423192b`); Phase 4 via PR #8 (`c920891`); Phase 5 staging prep via PR #9/#10; Phase 5.5 via PR #12/#13 (merged into `main`, deployed to staging, Square sandbox smoke-tested — see `SESSION_HANDOFF.md` for full detail). `main`'s HEAD at the time this branch was cut was `ab8ed98`. Old remote feature branches were deleted on GitHub after each merge — expect the same pattern for this branch.
- Auth baseline status: the owner-session, customer, vehicle, context, and estimate-approval slices remain in place and unchanged in scope.
- Current verified functionality: owner login/logout/me, protected chat, protected location resolution, owner-scoped context CRUD, customer CRUD/list/search/archive, vehicle CRUD/list/search/archive, saved estimate CRUD/revisioning/approval, Work Order conversion/list/detail/update/status/note flows, invoice generation/list/detail/issue/html/pdf flows, invoice payment recording/void/schedule/balance-derivation flows, notifications, and Square sandbox invoice push/refresh.

## Landing Page Redesign (in progress, uncommitted)

- Goal (owner request, 2026-07-10): add a new unauthenticated marketing landing page at `/` with working login access, shown before the authenticated dashboard ("OS system"), and apply the same graphite/off-white/steel/restrained-red palette and existing 3D rotor/caliper/diagnostic-tablet visual motif consistently across the whole authenticated app (replacing the previous electric-blue palette). This was an explicit, intentional request to re-theme the whole app, not scope creep.
- Files changed: `app/static/index.html` (new `<section class="marketing-site" data-view-panel="landing">` before `.app-shell`, reusing the existing `.hero-panel`/`.mechanic-stage`/`.capability-card`/`.principle-tags` classes for visual consistency, `<body class="marketing-mode">` default), `app/static/styles.css` (root CSS custom properties re-themed from blue to graphite/off-white/steel/red; ~35 hardcoded color literals throughout the file updated to match; new marketing-page-only CSS and a `.marketing-mode` body-class toggle appended; a global `:focus-visible` outline rule added), `app/static/app.js` (unauthenticated visitors to `/` now stay on the marketing landing page instead of being forced to `/login`; `/login`/`/approval` explicitly clear `marketing-mode` from the existing pathname branch in `initializeApp`), `tests/test_official_ui.py` (three new regression tests, see below).
- No real Landon Motor Works field photography was available, so the hero visual reuses the existing CSS-drawn 3D rotor/caliper/diagnostic-tablet scene (already used on the dashboard), recolored to match — not fabricated photos.
- Two CSP violations were found and fixed during this work (full detail in `KNOWN_ISSUES.md`): an inline `<script>` bootstrap (would have broken `/login`/`/approval` under the real `script-src 'self'` CSP — caught by independent review before it shipped) and a **pre-existing, unrelated** inline `style=""` attribute on the Square dashboard panel (violates `style-src 'self'`, present since the Square feature slice, never previously checked against a live CSP). Both fixed; regression tests added (`test_index_html_has_no_inline_scripts`, `test_index_html_has_no_inline_style_attributes`).
- Verification: `ruff format`/`ruff check .` clean, `pyright` 0 errors, `node --check app/static/app.js` clean, `pytest -q` 203 passed (200 pre-existing + 3 new: the two CSP regression tests above plus `test_marketing_landing_page_gating`). Independent review completed (`optimus-reviewer` agent) — one CRITICAL finding (the inline-script CSP issue) and fixed before this doc was written; re-verified live afterward.
- Live proof (2026-07-10): rebuilt the `backend` Docker image (which bakes in `app/static` at build time, unlike the `frontend` nginx service which bind-mounts it) and ran a real Playwright browser directly against `http://127.0.0.1:8000` (the only local surface that actually applies the FastAPI `security_headers` CSP middleware — the dev nginx frontend at `:5173` serves `app/static` via a bind-mounted `try_files` and does not route `/`/`/login`/`/approval` through the backend, so it does not exercise the CSP at all). Confirmed: unauthenticated `/` shows the marketing section with `.app-shell` hidden; `/login` and `/approval` correctly show the app shell with the right view active; zero CSP console violations on any of the three routes after the fixes (only the expected `401` on `GET /api/auth/me`, matching the project's established "expected auth guard" pattern).
- Not done / explicitly out of scope this session: no authenticated-dashboard screenshot was captured (no synthetic or real owner session was minted, consistent with this project's established caution around session-credential materialization) — the dashboard's re-theme was instead verified by confirming it shares the exact same CSS classes/variables already visually confirmed correct on the login page and landing page (both screenshotted). Nothing committed, pushed, or deployed — pending owner approval.

## Overview Dashboard & Approval Queue (in progress, uncommitted, same branch)

- Goal (owner request, 2026-07-11, following a `/plan` cycle the owner approved before implementation): replace the "Shop intelligence online" dashboard hero with a real, data-driven shop-management overview dashboard, using an owner-supplied reference financial-dashboard image as a **structural** reference only (layout/density/hierarchy) — not its branding, labels, colors, or values. Two scope decisions were confirmed with the owner up front: (1) the left nav gets real modules only, plus clearly-disabled "Coming soon" stubs for modules with zero backing data today (Service Desk, Diagnostics, Inspections, Scheduling, Technicians, Parts, Vendors, Reports); (2) charts use a vendored Chart.js rather than hand-rolled SVG.
- New backend: `app/dashboard_store.py` (new, read-only, owner-scoped aggregation module, same pattern as `customer_history_store.py`) + `GET /api/dashboard/summary?date_from=&date_to=` in `app/main.py` + new Pydantic response models in `app/models.py` (`DashboardSummaryResponse` and friends). No schema/migration changes — pure aggregation over existing `Invoice`/`WorkOrder`/`Estimate`/`InvoicePayment`/`PaymentSchedule`/`EstimateApprovalRequest` tables.
- Honesty guarantee: metrics with no real backing (**Gross Profit**, **Net Profit**, **Gross Profit Margin**, **Technician Utilization**, **Bay Utilization**) are never fabricated — OptimusOS has no COGS/wholesale-parts-cost or expense tracking, and no technician/bay-scheduling data model, so these render an honest "not available" state with the specific reason (e.g. "Connect parts-cost (COGS) tracking to display this metric"). Real metrics (Revenue, Labor/Parts Revenue, Average Repair Order, Open Work Orders, Awaiting Customer Approval, Approval Conversion Rate, Accounts Receivable Health, revenue-by-category breakdown, current-operations counts, financial obligations incl. real upcoming `PaymentSchedule` installments) are computed from real data with period-over-period comparison deltas.
- Shop Insights panel: server-side, rule-based (not AI-generated, labeled honestly) — overdue invoices, completed-but-not-invoiced work orders, work orders stalled in `waiting_for_parts` (using the actual status-transition timestamp, not `updated_at`, to avoid understating wait time), estimates stalled in `awaiting_approval` (using the actual `EstimateApprovalRequest.created_at` send time), and a declining-average-repair-order trend check. Each insight links to the real record.
- New **Approval Queue** nav item + `#view-approval-queue`: fully real, built entirely on the already-existing `GET /api/estimates?status=awaiting_approval` endpoint (no new backend route needed) — list + detail + "Open in estimator"/"Open customer" links, a nav badge, and 60s background polling matching the existing notifications-badge pattern.
- Chart.js v4.4.4 UMD build vendored (owner-approved exact source URL) into `app/static/vendor/chart.umd.min.js` + `LICENSE-chart.js` (MIT), loaded via a same-origin `<script src="/static/vendor/chart.umd.min.js" defer>` tag — `script-src 'self'`-compliant.
- The dashboard's pre-existing real, working features (the "Direct command" quick-chat box and the "Live systems" health panel) were preserved, just relocated into the new layout — not deleted.
- A real bug was found and fixed during live verification: Chart.js's `responsive:true` mode needs a CSS-sized parent container, not just canvas width/height attributes — without it, the per-metric-card sparkline canvases rendered with unbounded height and blew out the whole metric-card grid row. Fixed by wrapping each sparkline canvas in a `.metric-sparkline-frame` div with an explicit CSS height.
- Verification: `ruff format`/`ruff check .` clean, `pyright` 0 errors, `node --check app/static/app.js` clean, `pytest -q` 210 passed (203 prior + 6 new backend tests in `tests/test_dashboard_api.py` covering empty state, real-data aggregation correctness, waiting-on-parts counting, invalid date range rejection, and cross-user isolation, + 1 new frontend markup regression test in `tests/test_official_ui.py`).
- Live proof (2026-07-11): rebuilt the `backend` Docker image and, inside that container, seeded a **synthetic** owner (`dashboard-verify-*`, not the real business owner) with a real estimate → work order → completed → issued-invoice chain, a second work order left in `waiting_for_parts`, and a third estimate sent for real customer approval — all via the app's own store functions, no fabricated production data. Logged in as that synthetic user with a real Playwright browser against `http://127.0.0.1:8000` (the CSP-enforcing surface): confirmed real numbers flow through every metric card/gauge/chart/panel, the date-range filter re-fetches without a page reload, the Approval Queue lists and opens the real pending estimate, disabled nav stubs are correctly inert (Playwright's own `aria-disabled`-aware actionability check refused a normal click; a forced click also did nothing), mobile layout is usable, and there were **zero CSP violations and zero console errors**. The synthetic user and all its data were deleted afterward (cascade delete via the owner row) — nothing synthetic remains in the dev database.
- Not done / explicitly out of scope: no permanent automated Playwright test was added for this live click-through (matches this repo's existing pattern of one-time live proofs rather than committed browser-test infrastructure). Nothing committed, pushed, or deployed — pending owner approval.

## Work Order Slice

- Work Order backend status: implemented with canonical PostgreSQL persistence in `work_orders`, `work_order_status_events`, and `work_order_notes`, all owner-scoped and added by Alembic migration `007_work_orders`.
- Work Order conversion rule: only an `approved` estimate with an approved revision can convert; idempotency is enforced by a database unique constraint on `(estimate_id, estimate_revision_id)`.
- Work Order lifecycle status set: `pending_requirements`, `ready_to_schedule`, `scheduled`, `in_progress`, `waiting_for_parts`, `waiting_for_approval`, `completed`, `cancelled`.
- Work Order transition rule: `waiting_for_approval` exists in the enum only; no route transitions into it yet.
- Payment-plan rule: estimates approved with `split_payment` or `two_month_plan` convert to `pending_requirements`; transition to `ready_to_schedule` is blocked until both `deposit_received` and `authorization_confirmed` are true.
- Work Order notes rule: notes are append-only and explicitly labeled `internal` or `customer` for visibility separation.
- Work Order API surface:
  - `POST /api/estimates/{estimate_id}/work-order`
  - `GET /api/work-orders`
  - `GET /api/work-orders/{id}`
  - `PATCH /api/work-orders/{id}`
  - `POST /api/work-orders/{id}/status`
  - `POST /api/work-orders/{id}/notes`
- Work Order frontend status: static frontend now includes a `Work orders` navigation view with list/search/status filter, detail rendering, status controls, notes, and a `Create work order` action from an approved saved estimate.

## Invoice Slice

- Invoice backend status: implemented with canonical PostgreSQL persistence in `invoices` and `invoice_line_items`, added by Alembic migration `008_invoices`.
- Invoice creation rule: only a `completed` work order can generate an invoice; completion idempotently creates one owner-scoped `draft` invoice per work order via a unique constraint on `work_order_id`.
- Invoice snapshot rule: invoice rows store customer-safe customer and vehicle snapshots plus customer-facing line items and totals derived from the approved estimate revision used by the completed work order.
- Invoice status rule: Phase 2 only actively uses `draft` and `issued`; `partially_paid`, `paid`, `overdue`, and `void` remain reserved for Phase 3 payment tracking and later hardening.
- Invoice document rule: HTML and PDF outputs are rendered from invoice-safe fields only; internal estimate research reasoning, unselected competitor options, raw request overrides, and other forbidden internal fields are excluded.
- Invoice API surface:
  - `GET /api/invoices`
  - `GET /api/invoices/{id}`
  - `POST /api/invoices/{id}/issue`
  - `GET /api/invoices/{id}/html`
  - `GET /api/invoices/{id}/pdf`
- Invoice frontend status: static frontend now includes an `Invoices` navigation view with list/search/status filter, detail rendering, issue controls, HTML/PDF document actions, and a bridge from completed work orders into their generated invoice.

## Payment Tracking Slice (Phase 3)

- Payment backend status: implemented with canonical PostgreSQL persistence in `invoice_payments` and `payment_schedules`, added by Alembic migration `009_payments`, in a new `app/payment_store.py` module (an intentional, reviewed deviation from the plan's original file layout — `record_payment`/`void_payment` live separately from `app/invoice_store.py` and import its shared helpers read-only).
- Append-only ledger rule: `invoice_payments` rows are never updated or deleted. Voiding inserts a negative-amount reversal row (`reversal_of_payment_id` set); a DB-level `UniqueConstraint` on `reversal_of_payment_id` blocks double-voiding even under a request race, and a `CheckConstraint` enforces the amount-sign/reversal invariant.
- Derived-field rule: `invoice.status`, `total_paid`, `balance_due`, and `is_overdue` are always recomputed server-side from non-voided payments plus `due_at`, fresh at every read (`_to_read`); the physical `invoices.status` column is only a best-effort cache updated on payment-write paths. Client-supplied financial status is never accepted.
- Money-math rule: all payment/balance arithmetic uses `Decimal` (`_money()`, `ROUND_HALF_UP`, quantized to `0.01`); float conversion happens only at the Pydantic response boundary.
- Overpayment rule: rejected with `422`, no tolerance; corrections are void + re-record only. The overpayment check locks the invoice row (`SELECT ... FOR UPDATE`, Postgres-only — a no-op under SQLite tests) for the duration of `record_payment` so concurrent submissions against the same invoice serialize instead of both passing a stale balance check.
- Deposit rule: a payment with `applies_to=deposit` on a payment-plan work order (`split_payment`/`two_month_plan`) flips `deposit_received` to `true` in the same transaction if not already set; voiding that payment does **not** auto-revert it (documented limitation — the owner can flip it back via the existing `PATCH /api/work-orders/{id}`).
- Payment schedule rule: generated exactly once on `issue`, using an explicitly-flagged **placeholder default even split** (100% for `pay_in_full`; 50/50 for `split_payment`; roughly-thirds deposit/30-day/60-day for `two_month_plan`), with any rounding remainder absorbed into the final row so amounts always sum exactly to `invoice_total`. The real deposit/installment percentage split is still unconfirmed business policy — see `docs/context/BUSINESS_RULES.md`.
- No card/bank/payment-authorization fields exist anywhere in the new schema — `method_label` is free text only, by design, so there is nothing to leak.
- Payment API surface:
  - `POST /api/invoices/{id}/payments`
  - `POST /api/invoices/{id}/payments/{payment_id}/void`
  - `GET /api/invoices` / `GET /api/invoices/{id}` responses now also include `total_paid`, `balance_due`, `is_overdue`, `payments[]`, and `schedule[]`
- Payment frontend status: the existing invoice detail panel (not a parallel billing surface) now shows balance/paid summary, an overdue badge, payment history with void controls, a read-only schedule list, and a record-payment form.
- Explicitly out of scope for this slice (per owner decision 2026-07-08): any Square or other external payment processor, any live/billable payment API call, and any change to Square/external scheduling or the existing Work Order status lifecycle — Square integration is deferred to a distinct future phase with its own design/approval pass.

## Hardening Slice (Phase 4)

- Status: **Closed** (owner decision, 2026-07-09). Four of the roadmap's six deliverables landed as permanent test/script files; two (fresh-volume E2E flow, failure drills) were satisfied via a one-time manual live proof rather than new permanent automated Docker/E2E infrastructure. The owner has explicitly accepted the one-time proof as sufficient to close Phase 4 — a permanent automated fresh-volume E2E/failure-drill artifact remains unbuilt and is not planned unless separately requested.
- New files: `tests/test_isolation_sweep.py`, `tests/test_idempotency_audit.py`, `tests/test_document_exposure_scan.py`, `scripts/scan_logs_for_secrets.py`.
- Investigated and ruled out a suspected defect in `app/auth.py::get_current_auth_context` (Postgres-down error handling): it already wraps its DB access in `try/except SQLAlchemyError` returning a sanitized `503`; confirmed by code reading, a live drill, and independent + security review. No code changed.
- One-time live proof (2026-07-08) against an isolated `optimus_e2e` Docker Compose project (separate volumes/ports, same real hardened image): fresh-volume migration from empty to `009_payments (head)`; full Customer(seeded)→WorkOrder→Completion→Invoice→Payment→`paid` flow via real HTTP; clean secret-log scan; Redis-down/up and Postgres-down/up drills both showed sanitized responses and clean recovery with no backend restart; full-stack restart preserved all data; dev stack/volumes confirmed untouched throughout; clean teardown.
- Out of scope, unchanged: Square/external payment or scheduling integration, live/billable OpenAI calls.
- Merged to `main` via PR #7 (Phase 3, commit `423192b`) and PR #8 (Phase 4, commit `c920891`) on 2026-07-09.

## Staging Prep (Phase 5, in progress)

- Status: **real staging infrastructure is live and reachable.** DigitalOcean droplet (`137.184.102.247`) running the stack via `docker-compose.yml` + `ops/docker-compose.staging.yml`; domain `optimus-os.com` registered through Cloudflare with `staging.optimus-os.com` proxied (Flexible SSL, Always Use HTTPS on). `https://staging.optimus-os.com/health` and `/ready` confirmed reachable end to end from outside the droplet.
- Droplet is currently on `main` (`36b861b`) — it predates the invoice-button fix (`1139499`) and the optimusctl override fix (`7d665c8`). Deploy method decided (checkout `ops/staging` on the droplet); exact owner one-liners are in `SESSION_HANDOFF.md` Owner action items. HSTS confirmed live on the public domain 2026-07-09.
- Code/process changes made and rehearsed against the local dev stack: HSTS header added to `app/main.py` (env-gated on `frontend_origin` being https, same pattern as the existing Secure-cookie check); `scripts/optimusctl.sh` gained `restore` (scratch-database-only, with a live-db-name guard sourced from `.env`, a reserved-system-db denylist, and an identifier-shape check), `rollback` (image-tag-based, sudo-aware), and `migrate-down` subcommands, and (2026-07-09, `7d665c8`) `COMPOSE_OVERRIDE_FILE` support so the staging droplet keeps its public port binding through every subcommand.
- A separately reported frontend bug (invoice detail buttons — "Open work order/HTML/PDF" — staying disabled after being opened from a work order) was root-caused to an async race condition in `app/static/app.js` and fixed with a selection-version guard; live-tested with Playwright network interception to deterministically prove both the bug and the fix. See `docs/context/SESSION_HANDOFF.md` for full detail.
- Two secret-exposure incidents occurred and were disclosed this session (a `docker compose config` dump, and a mangled-terminal-paste incident) — see `docs/context/KNOWN_ISSUES.md` and `SESSION_HANDOFF.md`.
- Independent review + security review completed on the earlier local-prep changes; four real findings fixed same-day: a sudo-docker regression risk in the new rollback code, a live-database-guard reading the wrong environment source, a missing PostgreSQL reserved-name denylist, and a doc PR/phase mislabeling. See `docs/context/KNOWN_ISSUES.md` for detail.
- Not yet started: separate staging PostgreSQL/Redis with distinct credentials from any other environment beyond what's already set, secrets-store handling beyond `.env` on the host, external `/health`+`/ready` monitoring/alerting, disk-space alerting.

## Verification Status

- Formatting and static checks passed on 2026-07-08:
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .`
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright`
  - `node --check app/static/app.js`
- Full automated test suite passed on 2026-07-08:
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
- Targeted Work Order test coverage passed on 2026-07-08 in `tests/test_work_orders_api.py`, covering the roadmap categories for auth rejection, approved conversion, non-approved rejection, idempotency, revision preservation, copied labor/parts/totals, cross-user isolation, valid transitions, invalid transitions, payment prerequisite blocking, note visibility separation, cancellation, restart persistence, and sanitized storage failures.
- Docker and migration checks passed on 2026-07-08:
  - `docker compose config -q`
  - `docker compose build backend worker`
  - `docker compose up -d backend worker frontend`
  - `docker compose exec -T backend alembic heads` → `008_invoices (head)`
  - `docker compose exec -T backend alembic upgrade head`
  - `docker compose exec -T backend alembic current` → `008_invoices (head)`
- Non-billable live Work Order proof passed on 2026-07-08 against the rebuilt Docker stack:
  - seeded an approved estimate fixture and converted it through the real UI
  - exercised `pending_requirements -> ready_to_schedule -> scheduled -> in_progress -> waiting_for_parts -> in_progress -> completed`
  - added both internal and customer-visible notes
  - restarted `backend` and `worker` and verified persistence after restart
  - proved live cross-user isolation with a second synthetic owner: `GET /api/work-orders/{id}` and duplicate conversion attempts returned `404`
  - proof result summary: `estimate_id=63`, `work_order_id=2`, `final_status=completed`, `notes_count=2`, `status_events=7`
- Independent review completed on 2026-07-08. Follow-up fixes shipped for:
  - blocked payment-plan transitions no longer appear as available next statuses
  - "Open estimate" from a work order now fetches the estimate when it is not already cached client-side
  - adding a note refreshes the parent work order `updated_at` so list recency matches execution activity
- Security review completed on 2026-07-08 with no new findings in the Work Order diff.
  - Reviewed surfaces: owner scoping on all work-order queries/routes, cross-user access behavior, append-only status/note writes, payment-plan prerequisite gating, and frontend HTML rendering/escaping for work-order content
  - Result: no auth bypass, no customer-document exposure regression, no raw-storage error leak, and no XSS introduced in the new work-order UI rendering path
- Phase 2 automated verification passed on 2026-07-08:
  - full suite still green after invoice changes
  - `tests/test_invoices_api.py` covers completed-work-order invoice generation, duplicate-completion idempotency, totals preservation, issue stamping, HTML/PDF forbidden-field exclusion, cross-user isolation, historical snapshot persistence, restart persistence, and sanitized storage failures
  - follow-up regression coverage now proves a failed completion-time invoice create rolls back the work-order status update instead of persisting a `completed` work order without an invoice
  - follow-up regression coverage now also proves non-canonical fee items are included in `fees_total`, long/multiline invoice line items survive HTML/PDF generation, and cross-user denial applies to invoice issue/PDF routes in addition to list/detail/html
- Phase 2 post-review fixes shipped on 2026-07-08:
  - work-order completion and invoice creation now succeed or roll back atomically in the same transaction
  - invoice HTML now uses the shipped `/static/invoice.css` asset so the rendered document remains styled under the app's existing `style-src 'self'` CSP
  - invoice `fees_total` now derives from all approved fee items instead of assuming only the three canonical fee codes
  - invoice line-item descriptions now use `Text` in the committed `008_invoices` schema/model instead of a narrower `String(240)` cap
  - PDF rendering now wraps long/multiline customer-visible content instead of truncating raw lines
  - invoice selection now re-renders the list so the active-row highlight stays in sync with the selected invoice
- Non-billable live invoice proof passed on 2026-07-08 against the rebuilt Docker stack:
  - completed a live work order into invoice generation
  - opened the invoice through the real owner UI from the work-order detail view
  - issued the draft invoice through the UI
  - retrieved live HTML and PDF document outputs with `200` responses and `%PDF-1.4` output prefix
  - retrieved `/static/invoice.css` with `200` and confirmed the invoice HTML references it
  - restarted `backend` and `worker` and verified the issued invoice still loaded with the same invoice number and PDF response
  - proved live cross-user isolation with a second synthetic owner receiving `404` on invoice access
  - proof result summary after the rebuilt-stack re-run: `estimate_id=69`, `work_order_id=6`, `invoice_id=4`, `invoice_number=INV-00004`, `final_status=completed`, `issued_status=issued`, `cross_user_status=404`
- Phase 2 security review completed on 2026-07-08 with no findings.
  - Reviewed surfaces: completion-triggered invoice creation, owner scoping on list/detail/document routes, HTML escaping, PDF field narrowing, invoice snapshot contents, and invoice document exposure boundaries
  - Result: no auth bypass, no cross-user leak, no internal-research leak in document output, and no new unsafe HTML rendering path
- Phase 2 independent re-review completed on 2026-07-08 with no remaining findings after the fixes.
- Phase 3 automated verification passed on 2026-07-08:
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check app/db_models.py app/invoice_store.py app/main.py app/models.py app/payment_store.py alembic/versions/009_payments.py tests/test_payments_api.py` → clean (repo-wide `ruff format --check .` flags 4 pre-existing files unrelated to this diff — confirmed via `git stash` that the drift predates this session)
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` → all checks passed
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright` → 0 errors
  - `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` → 165 passed (16 new in `tests/test_payments_api.py`, all Phase 1/2 tests still green)
  - `node --check app/static/app.js` → OK
- Phase 3 Docker/migration verification passed on 2026-07-08:
  - `docker compose config -q`
  - `docker compose build backend worker`
  - `docker compose up -d backend worker frontend`
  - `docker compose exec -T backend alembic heads` → `009_payments (head)`
  - `docker compose exec -T backend alembic upgrade head`
  - `docker compose exec -T backend alembic current` → `009_payments (head)`
  - rollback rehearsal: `alembic downgrade 008_invoices` then `alembic upgrade head` → clean round-trip, back at `009_payments (head)`
- Phase 3 independent review completed on 2026-07-08: no correctness bugs, no regressions (`app/work_order_store.py` confirmed untouched), all 16 planned test cases present, cross-user isolation confirmed on both new routes. Two minor, accepted architecture-drift notes: payment logic landed in a new `app/payment_store.py` module rather than inside `invoice_store.py`, and `InvoicePaymentCreate.amount` has an added `le=1_000_000` upper bound not in the original plan text — both harmless and reflected in this doc.
- Phase 3 security review completed on 2026-07-08: no critical/high findings. One medium finding (overpayment check not race-safe against concurrent requests on the same invoice) was fixed same-day by adding a `SELECT ... FOR UPDATE` row lock in `record_payment`; full gates re-ran green after the fix.
- Non-billable live proof passed on 2026-07-08 against the rebuilt Docker stack (fixture-seeded estimate, no OpenAI call, owner/session constructed directly against the real DB without touching `.env`):
  - two-month-plan estimate → work order conversion → blocked premature scheduling (prereqs unmet) → deposit payment recorded → `deposit_received` flipped by the payment itself → invoice issued with a 3-row schedule (`Deposit`/`Installment 1`/`Installment 2`, summing exactly to `invoice_total` in Decimal) → status `partially_paid` → overpayment rejected → balance paid in full → status `paid`, balance `0` → deposit payment voided → status recomputed back to `partially_paid`, balance `186.31`, `deposit_received` unchanged (`true`) → double-void rejected
  - restarted `backend`/`worker` and confirmed identical state after restart: `invoice_status=partially_paid`, `total_paid=372.62`, `balance_due=186.31`, `payment_count=3`, `schedule_count=3`, `work_order_status=completed`, `deposit_received=true`
  - proved live cross-user isolation with a second synthetic owner: `GET /api/invoices/{id}`, `POST /api/invoices/{id}/payments`, and `POST /api/invoices/{id}/payments/{payment_id}/void` all returned `404`
  - proof result summary: `estimate_id=71`, `work_order_id=8`, `invoice_id=6`, `owner_user_id=12`

## Next Approved Implementation Phase

- Phase 1 is closed and merged to `main`.
- Phase 2 is closed and merged to `main`.
- Phase 3 is closed and merged to `main` (PR #7, `423192b`).
- Phase 4 is closed and merged to `main` (PR #8, `c920891`) — owner accepted the one-time live proof as sufficient for the fresh-volume E2E/failure-drill deliverables; no permanent automated version is planned unless separately requested.
- Phase 5 — Private Staging is the active phase on `ops/staging`. Real deployment actions (host/provider selection, DNS, TLS, secrets store, alerting) require an explicit owner decision before proceeding — see `docs/context/SESSION_HANDOFF.md`.
