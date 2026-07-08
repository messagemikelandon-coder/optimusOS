# Current State

Purpose: concise operational snapshot of the verified current repository state.
Information owner: repository maintainers and the current Codex session author.
Read when: before every task, together with `SESSION_HANDOFF.md`.
Update when: the branch, working status, live stack status, migrations, or quality-gate results change.
Last verified date: 2026-07-08.
Relevant sources: `git status --short --branch`, `git rev-parse HEAD`, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`, `node --check app/static/app.js`, `docker compose config -q`, `docker compose build backend worker`, `docker compose up -d backend worker frontend`, `docker compose exec -T backend alembic heads`, `docker compose exec -T backend alembic upgrade head`, `docker compose exec -T backend alembic current`, non-billable Playwright/API proof commands run from the local shell.

## Operational Snapshot

- Active development phase: **Phase 2 — Work Completion and Invoice PDF is implemented, independently reviewed, live-proofed, and ready for commit/push before Phase 3 starts.**
- Current branch: `feat/invoices`.
- Current HEAD: `f6dd75d774e99bd2da7c0c7aa96443f0c2497a34` (`feat: complete work order phase`).
- Git working state: Phase 1 is committed and pushed to `origin/feat/work-orders`; Phase 2 invoice implementation, tests, UI, migration, and context updates are staged on `feat/invoices` for commit/push.
- Auth baseline status: the owner-session, customer, vehicle, context, and estimate-approval slices remain in place and unchanged in scope.
- Current verified functionality: owner login/logout/me, protected chat, protected location resolution, owner-scoped context CRUD, customer CRUD/list/search/archive, vehicle CRUD/list/search/archive, saved estimate CRUD/revisioning/approval, Work Order conversion/list/detail/update/status/note flows, and invoice generation/list/detail/issue/html/pdf flows.

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
  - invoice line-item descriptions now use `Text` in the uncommitted `008_invoices` schema/model instead of a narrower `String(240)` cap
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

## Remaining Work Before Phase 2 Can Be Closed

- No engineering or verification gates remain open for the Phase 2 slice.
- Commit and push still require explicit owner approval before execution.

## Next Approved Implementation Phase

- Phase 1 is closed and pushed.
- Phase 2 should be committed and pushed before Phase 3 starts so the roadmap remains phase-gated and the handoff baseline stays clean.
