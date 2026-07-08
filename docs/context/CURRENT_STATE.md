# Current State

Purpose: concise operational snapshot of the verified current repository state.
Information owner: repository maintainers and the current Codex session author.
Read when: before every task, together with `SESSION_HANDOFF.md`.
Update when: the branch, working status, live stack status, migrations, or quality-gate results change.
Last verified date: 2026-07-08.
Relevant sources: `git status --short --branch`, `git rev-parse HEAD`, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`, `node --check app/static/app.js`, `docker compose config -q`, `docker compose build backend worker`, `docker compose up -d backend worker frontend`, `docker compose exec -T backend alembic heads`, `docker compose exec -T backend alembic upgrade head`, `docker compose exec -T backend alembic current`.

## Operational Snapshot

- Active development phase: **Phase 1 — Work Orders is complete and verified.** Phase 2 — Work Completion and Invoice PDF is the next implementation slice.
- Current branch: `feat/work-orders`.
- Current HEAD: `6d0c332f045b4a291c6f06fd6c87675505f4e503` (`chore: add AI coordination pack`).
- Git working state: Work Order implementation, review-fix follow-ups, and context compression updates are present in the worktree and ready to be committed as the Phase 1 baseline.
- Auth baseline status: the owner-session, customer, vehicle, context, and estimate-approval slices remain in place and unchanged in scope.
- Current verified functionality: owner login/logout/me, protected chat, protected location resolution, owner-scoped context CRUD, customer CRUD/list/search/archive, vehicle CRUD/list/search/archive, saved estimate CRUD/revisioning/approval, and now Work Order conversion/list/detail/update/status/note flows.

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
  - `docker compose exec -T backend alembic heads` → `007_work_orders (head)`
  - `docker compose exec -T backend alembic upgrade head`
  - `docker compose exec -T backend alembic current` → `007_work_orders (head)`
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

## Next Approved Implementation Phase

- Phase 1 is closed.
- The next slice is **Phase 2 — Work Completion and Invoice PDF**.
