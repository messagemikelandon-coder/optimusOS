# Plans

Purpose: durable phase checklist for OptimusOS from the verified Estimate Approval slice through to a controlled customer pilot. This is the single "where are we" reference — read it before re-deriving a roadmap.
Information owner: repository maintainers (roadmap authored 2026-07-07).
Read when: starting any new slice, or checking overall project sequencing.
Update when: a phase's acceptance criteria are met, or the sequence changes.
Last verified date: 2026-07-11 (Phase 5.6 sub-phases 0 & 1 completed and reviewed same day).
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/KNOWN_ISSUES.md`, `docs/context/SESSION_HANDOFF.md`, `AGENTS.md`, `CLAUDE.md`.

## Standing rules (apply to every phase below)

- PostgreSQL is the source of truth. The context manager is assistive memory only — never store full customer, vehicle, estimate, work order, invoice, payment, approval-token, or payment-authorization records there.
- Never disclose supplier cost, markup, margin, internal pricing logic, approval tokens, session cookies, API keys, or raw database errors to customer-facing surfaces or logs.
- Every business record is scoped to the authenticated owner/user. Cross-user isolation is tested at every slice — a failing isolation test is a hard stop for the whole project, not just that slice.
- Every slice ships backend + frontend + tests + non-billable runtime proof + docs + a replaced `SESSION_HANDOFF.md`.
- One agent owns one branch/worktree at a time. The implementing agent never grades its own slice — an independent review (different agent) is required before a slice is considered done.
- Do not weaken Estimate Approval validation to make downstream work easier.
- No live OpenAI calls, commits, pushes, merges, or deploys without explicit current-turn approval.

## Phase checklist

### Phase 0 — Freeze and back up Estimate Approval
- [x] Estimate Approval live-verified against a real OpenAI call (2026-07-06).
- [x] Verified files committed (`ce39561` "verify: complete estimate approval live proof").
- [x] Branch renamed `feat/vehicle-management` → `feat/estimate-approval`.
- [x] Pushed to GitHub — `origin/feat/estimate-approval` confirmed at `ce39561`.
- [x] `AGENTS.md` / AI Coordination Pack committed locally on the Work Orders branch as `6d0c332` (`chore: add AI coordination pack`).
- [x] The local `feat/work-orders` branch remained local-only until explicit push approval was granted in the current session.
- [x] `SESSION_HANDOFF.md` now reflects the local branch reality instead of the stale estimate-approval branch.

**Acceptance:** commit SHA recorded, GitHub backup confirmed (local HEAD == origin HEAD), `SESSION_HANDOFF.md` current, Work Orders not started before backup is confirmed.

### Phase 1 — Work Orders
**Goal:** an approved estimate converts to a work order without re-entering customer, vehicle, labor, parts, or pricing data.

Branch: `feat/work-orders`, from `feat/estimate-approval` (only after Phase 0 fully checked off).

Key rules:
- Convert only from an `approved` estimate revision; conversion keyed by a DB-level unique constraint on `(estimate_id, revision_id)` so repeats return the existing row (idempotent by construction, not app-logic).
- Customer/vehicle context comes from the approved revision's existing snapshot — no new copies.
- Status transitions are server-controlled via one transition table; every transition recorded in an append-only `work_order_status_events` table.
- Payment-plan work orders start `pending_requirements` (gated on `deposit_received` / `authorization_confirmed` booleans, owner-settable only); non-payment-plan orders start `ready_to_schedule`.
- `waiting_for_approval` status exists in the enum for future change-order support but **nothing routes to it yet** — change orders are their own future slice, not part of Phase 1.
- No real payment processing.

Statuses: `pending_requirements`, `ready_to_schedule`, `scheduled`, `in_progress`, `waiting_for_parts`, `waiting_for_approval`, `completed`, `cancelled`.

API: `POST /api/estimates/{estimate_id}/work-order`, `GET /api/work-orders`, `GET /api/work-orders/{id}`, `PATCH /api/work-orders/{id}`, `POST /api/work-orders/{id}/status`, `POST /api/work-orders/{id}/notes`.

Frontend: list page, detail page (status controls, notes, status history, blocked-transition explanation), "Create work order" action from an approved estimate.

Required tests: unauthenticated rejection; approved-estimate conversion; draft/declined/awaiting-approval rejection; duplicate-conversion idempotency; approved revision preserved; labor/parts/totals copied correctly; cross-user isolation; valid status transitions; invalid status transitions; payment-plan prerequisite blocking; notes visibility separation; cancellation; restart persistence; sanitized dependency failures.

- [x] Implemented in source: backend store/routes/models, Alembic migration `007_work_orders`, static frontend list/detail/status/notes flow, and targeted regression tests.
- [x] Verified complete:
  - all 14 roadmap test categories covered in `tests/test_work_orders_api.py`
  - full suite green
  - `ruff` / `pyright` green
  - Docker rebuild green
  - Alembic script head and live DB head both at `007_work_orders`
  - non-billable live browser/API proof of convert → status walk → notes → restart persistence
  - explicit live cross-user isolation proof
  - independent review completed and follow-up fixes applied
  - security review completed with no findings
  - context docs updated to the current local branch state

**Acceptance:** all endpoints live; all 14 test categories pass; full suite stays green; ruff/pyright clean; Docker rebuild + migration `007_work_orders` applied; non-billable browser proof of convert → status walk → notes → restart persistence; cross-user isolation proven at the API level; independent review + security review pass; docs + handoff updated. No live OpenAI call needed for this slice.

### Phase 2 — Work Completion and Invoice PDF
**Goal:** completing a work order generates a customer-facing Landon Motor Works invoice.

Branch: `feat/invoices`, from the merged/verified Phase 1 state.

- Migration `008_invoices`: `invoices` (owner-scoped, FK to work order + estimate revision, server-calculated totals snapshot), `invoice_line_items` (customer-facing values only — supplier cost/markup never populate these columns).
- Completion of a work order idempotently creates a `draft` invoice (unique constraint on `work_order_id`); an explicit "issue" action moves it to `issued` and stamps `due_at`.
- Build the customer-facing document as server-rendered **HTML first**, reusing the narrow-model exposure pattern from `EstimateApprovalPublicView`; verify all content/exclusion tests against the HTML; add PDF rendering as a second layer over the same template once HTML is proven. If this slice runs long, split PDF rendering into its own follow-up mini-slice rather than letting Phase 2 sprawl.
- PDF library is a new dependency touching the deployment image — flag it explicitly in review, don't slip it in.
- Statuses: `draft`, `issued`, `partially_paid`, `paid`, `overdue`, `void` — the payment-driven transitions (`partially_paid`/`paid`/`overdue`) are stubbed until Phase 3 and must be documented as such, not implemented early.

Required tests: invoice generated on completion; duplicate completion does not duplicate invoice; totals preserved; PDF generated; PDF excludes forbidden internal fields (supplier cost, markup, margin, internal notes, and any other policy-forbidden field); cross-user isolation; historical snapshot persistence; restart persistence.

- Implemented in source: backend invoice store/routes/models, Alembic migration `008_invoices`, owner-facing invoice UI list/detail/issue/document flow, and targeted regression tests in `tests/test_invoices_api.py`.
- Verified complete:
  - invoice generated on work-order completion
  - duplicate completion remains idempotent
  - totals and customer-safe line items preserved
  - HTML and PDF document outputs generated
  - forbidden-field exclusion checks pass for HTML/PDF output
  - cross-user isolation proven in tests and live proof
  - historical snapshot persistence proven after customer/vehicle updates
  - restart persistence proven in tests and live proof
  - full suite green
  - `ruff` / `pyright` green
  - Docker rebuild green
  - Alembic script head and live DB head both at `008_invoices`
  - non-billable live proof of completion → invoice issue → HTML/PDF retrieval → restart persistence
  - independent review completed and follow-up fixes applied for atomic completion/invoice creation and CSP-safe invoice styling
  - independent review follow-up also fixed full-fee aggregation, long-description schema safety, long/multiline PDF rendering, and invoice-list selection refresh
  - security review completed with no findings
  - independent re-review completed with no remaining findings
- [x] Commit/push the verified Phase 2 slice before starting Phase 3 (`85e9bce`, pushed to `origin/feat/invoices` on 2026-07-08)

**Acceptance:** all 8 test categories pass; PDF text-extraction test asserts forbidden fields never appear; idempotent completion; restart persistence; reviews pass; docs updated.

### Phase 3 — Payment Tracking
**Goal:** track invoice payments, deposits, installments, balances, and overdue state without live payment processing.

Branch: `feat/payment-tracking`.

- Migration `009_payments`: `invoice_payments` (append-only — amount, method label, recorded_at, note, `reversal_of_payment_id` for reversals; **no card/bank fields in the schema at all**, so there is nothing to leak), `payment_schedules` (installments for the two-month plan).
- Balance = server-side Decimal sum over non-voided payments; invoice status derived server-side, never client-supplied.
- Overdue computed against `due_at` with an injectable clock so tests don't sleep or fake system time.
- Overpayment: reject by default (explicit, tested); corrections go through void + re-record, never delete.
- Recording a deposit payment satisfies the linked work order's `deposit_received` prerequisite.

Required tests: full payment; partial payment; deposit; installments; overpayment rejection; void/reversal; invoice status updates; overdue calculation; cross-user isolation; restart persistence. Plus Decimal-precision regression tests — no float arithmetic anywhere in money paths.

- [x] Implemented in source: backend store (`app/payment_store.py`), models, Alembic migration `009_payments`, extended owner-facing invoice detail UI, and 16 targeted regression tests in `tests/test_payments_api.py`.
- [x] Owner decision recorded 2026-07-08: this phase is an internal append-only ledger only — no Square/external payment processor, no live/billable calls, no change to Square/external scheduling or the Work Order status lifecycle. Square is deferred to its own future phase. Payment-schedule percentage split uses an explicitly flagged placeholder (even default split) pending real business-rule confirmation.
- [x] Verified complete:
  - all 16 required test categories covered, full suite green (165 passed)
  - `ruff` / `pyright` green on the touched files and repo-wide
  - Docker rebuild green; Alembic script head and live DB head both at `009_payments`; downgrade/upgrade rollback rehearsed cleanly
  - non-billable live proof: deposit payment flips `deposit_received`, schedule generated once and sums exactly to `invoice_total` in Decimal, overpayment rejected, void recomputes balance/status without reverting `deposit_received`, double-void rejected, restart persistence confirmed, cross-user isolation returns `404` on both new routes
  - independent review completed: no correctness bugs, no regressions, `app/work_order_store.py` confirmed untouched; two minor accepted deviations documented (payment logic in its own module; an added upper bound on payment amount)
  - security review completed: one medium finding (overpayment check not race-safe) fixed same-day with a `SELECT ... FOR UPDATE` row lock; no other findings
  - context docs updated to reflect the current local branch state
- [ ] Commit/push the verified Phase 3 slice — **awaiting explicit commit/push approval**, not yet performed.

**Acceptance:** all listed test categories pass; full suite stays green; ruff/pyright clean; Docker rebuild + migration `009_payments` applied with rollback rehearsed; non-billable live proof of deposit/overpayment/void/overdue/restart/cross-user behavior; reviews pass; docs updated. Met in full except the commit/push step, which requires explicit owner approval.

### Phase 4 — Full Local MVP Hardening
**Goal:** prove the complete local flow end to end. Proof slice only — no new product features except fixes for what it finds.

- One automated, non-billable, deterministic E2E test: Customer → Vehicle → Estimate → Approval → Work Order → Completion → Invoice → Payments → paid, against the real Docker stack, **on a fresh volume + migrations** (not the long-lived dev database everything so far has run against).
- Second-owner isolation sweep across every record type created by the first user.
- Failure drills: Redis down, PostgreSQL down, full restart — all with sanitized errors and clean recovery.
- Full-log secret scan, formalized into a reusable script.
- Customer-document exposure scan across every customer-facing HTML/PDF surface.
- Idempotency audit: re-fire every conversion/completion/issue action twice, assert no duplicates.
- One paid, explicitly-authorized live estimate generation as the E2E entry point **only if approved that turn**; otherwise the seeded-estimate path stands in for it.

**Exit criterion:** everything above green in a single clean run from `docker compose up` on a fresh volume.

- [x] Second-owner isolation sweep: `tests/test_isolation_sweep.py` — one chain, one second-owner session, every record type; closes a real pre-existing gap (vehicle update/archive/list were never isolation-tested).
- [x] Idempotency audit: `tests/test_idempotency_audit.py` — repeated status transition, repeated issue, repeated full-payment request all proven non-duplicating.
- [x] Full-log secret scan script: `scripts/scan_logs_for_secrets.py` — reusable CLI, never prints matched text, covers OpenAI keys/generic secret labels/any credentialed connection URL/session-cookie value/approval-token-shaped strings.
- [x] Customer-document exposure scan: `tests/test_document_exposure_scan.py` — invoice HTML/PDF and the public estimate-approval view checked against a shared forbidden-marker list.
- [x] Fresh-volume E2E test + failure drills (Redis down, Postgres down, full restart): satisfied via a **one-time manual live proof** on 2026-07-08 against an isolated `optimus_e2e` Docker Compose project, not a permanent committed automated test. Evidence in `docs/context/SESSION_HANDOFF.md`. **Owner accepted this as sufficient on 2026-07-09** — a permanent automated version is not planned unless separately requested.
- [x] No live/billable OpenAI call made — seeded-estimate path used, as allowed.
- Independent review and security review both completed 2026-07-08 on the four new files; two minor issues found and fixed same-day (secret-scan regex gap, docstring honesty about test overlap). No findings on the (ruled-out) suspected `app/auth.py` defect.
- [x] Committed and merged to `main` via PR #8 (`c920891`) on 2026-07-09.

**Phase 4 is closed.**

### Phase 5 — Private Staging
Branch: `ops/staging`, from `main` at `c920891`.

- Separate host/environment; separate PostgreSQL + Redis with distinct credentials; synthetic data only, no real customers.
- Private domain + HTTPS, HSTS, secure cookies flipped on (currently `false` locally — verify it's env-driven).
- Secrets injected from environment/secrets store, never committed.
- Migration strategy as an explicit deploy step with a rehearsed downgrade.
- Backups: nightly `pg_dump`, **restore actually rehearsed once** into a scratch database.
- Monitoring on `/health` + `/ready`, error-log alerting, disk-space alerting.
- Rollback rehearsed once (previous image tag retained).
- Decide *where* staging will live during Phases 1–3, so Phase 5 doesn't stall on unmade infrastructure decisions.

**Progress (2026-07-09):**

- [x] Secure cookies confirmed already env-driven: `settings.frontend_origin.lower().startswith("https://")` in `app/auth.py` — no code change needed, just confirmed by reading the code.
- [x] HSTS header added to `app/main.py`'s `security_headers` middleware, same env-gating pattern as the Secure cookie flag; regression tests in `tests/test_security_headers.py`.
- [x] Migration downgrade formalized as an explicit deploy step: `scripts/optimusctl.sh migrate-down <revision>`, rehearsed once against the dev stack (`009_payments` → `008_invoices` → back to head).
- [x] Backup/restore rehearsed: `scripts/optimusctl.sh restore <dump-file> [target-db]` added (restores into a scratch database only, with an identifier-shape check, a live-database-name guard read from `.env` — not the ambient shell — and a PostgreSQL reserved-name denylist). Rehearsed once: `backup` → `restore` into `optimus_os_restore_check`, row counts confirmed matching the live DB across `user_accounts`/`customers`/`invoices`/`invoice_payments`.
- [x] Rollback mechanism added and rehearsed once: `scripts/optimusctl.sh rollback` (retags `:previous` back to `:latest`, sudo-aware). Rehearsed by deliberately breaking the backend (retagged to a dummy image), confirming `/health` failed, then running `rollback` and confirming full recovery.
- [x] Independent review + security review completed on all of the above; findings (sudo-docker regression risk, live-db-guard env-source bug, missing reserved-db-name denylist, a doc PR/phase mislabeling) all fixed and re-verified. See `docs/context/KNOWN_ISSUES.md`.
- [x] Infrastructure decision made (ADR-011, `docs/context/DECISIONS.md`): staging will run on a DigitalOcean droplet, domain registered through Cloudflare (also solves HTTPS termination via Cloudflare's proxy).
- [x] Owner created the DigitalOcean droplet (`137.184.102.247`) and registered `optimus-os.com` through Cloudflare; stack deployed at `/opt/optimus-server`; `https://staging.optimus-os.com/health` + `/ready` verified reachable end to end (2026-07-09). HSTS confirmed live on the public domain.
- [x] `scripts/optimusctl.sh` `COMPOSE_OVERRIDE_FILE` support added (`7d665c8`) so droplet operations keep the staging port binding.
- [x] **Droplet redeployed 2026-07-10** (owner-authorized direct SSH execution): `ops/staging` had already merged into `main` via PR #11 on GitHub (branch deleted after merge, same pattern as PR #10), so the droplet fast-forwarded `main` `36b861b`→`b38a811` (clean, no conflicts) instead of switching branches. `COMPOSE_OVERRIDE_FILE` set in droplet `.env`; `scripts/optimusctl.sh update` rebuilt and restarted; `status` confirmed frontend at `0.0.0.0:80->80/tcp` (override held); external curl from this machine confirmed `selectionVersion` present in the served `app.js` through Cloudflare — invoice-button fix is live on `https://staging.optimus-os.com`.
- [ ] **Owner action still pending**: one full browser login on staging with the rotated password, and the manual invoice-button repro click-through (browser-only checks, not agent-performable).
- [ ] Not started: separate staging PostgreSQL/Redis with distinct credentials, secrets-on-host beyond `.env`, `/health`+`/ready` external monitoring/alerting, disk-space alerting.

### Phase 5.5 — Feature slice: estimate cleanup, customer history, notifications, Square sandbox — SHIPPED

Owner-approved 2026-07-09. Implemented by **Claude** on branch `agent/claude/notify-history-square` on 2026-07-10 (the owner's /goal directive required same-session delivery). Merged into `main` via PR #12 + #13 on GitHub (branch deleted after merge, same pattern as prior staging PRs). Deployed to the staging droplet and verified live on `https://staging.optimus-os.com` same day. Full spec in `docs/context/SESSION_HANDOFF.md`.

- [x] Slice 1 — retired transient `POST /api/estimate` (every estimate the UI creates is persisted with approve/decline tracking); 3 tests ported.
- [x] Slice 2 — `GET /api/customers/{id}/history` aggregator + customer-detail history panel (estimates with approved/declined status, work orders, invoices with live balance/overdue).
- [x] Slice 3 — `notifications` table (migration `010_notifications_square`, includes Square invoice columns) + owner feed API + Notifications tab with unread badge and 60s poll; in-transaction hooks at all seven status-change producers.
- [x] Slice 4 — Square Invoices sandbox integration (config-gated `square_configured`; production structurally unreachable; Square never writes the local payment ledger).
- [x] Gates: ruff/pyright/pytest (200 passed) /node clean; alembic 009↔010 round-trip rehearsed on the compose Postgres; live curl proofs (auth gates, served assets, real schema).
- [x] Independent review completed (no CRITICAL; three IMPORTANT findings fixed/documented — client-leak fix, pre-existing transaction gap recorded in KNOWN_ISSUES, coverage gap carried; unique Square-id index added). Gates re-run green.
- [x] Committed, pushed, and merged into `main` (PRs #12/#13 on GitHub).
- [x] **Local Square sandbox smoke test completed 2026-07-10** with real owner-created sandbox credentials, against the real Square sandbox API (no stubs): built a full customer→estimate→approved→completed-work-order→issued-invoice chain via direct store calls (non-billable — no OpenAI call), pushed it to Square, got back a real Square invoice id + live pay link, confirmed refresh works, and confirmed the local payment ledger stays untouched (Square reported the invoice UNPAID; local `total_paid`/`balance_due`/payment-row-count all correct and independent of Square's state). Found and the owner fixed one real config bug: `SQUARE_LOCATION_ID` had been set to the Square **Application ID** by mistake — corrected to the real sandbox location id from `GET /v2/locations`. Two minor non-blocking findings also surfaced: Square's live validator rejects `.test`-TLD emails (our own fixture-seeding convention, not a real-customer risk) and requires E.164 phone format (our customer records store free-text phone) — both would currently surface as a generic 502, not a defect, just an opportunity for friendlier error messages later.
- [x] **Deployed to the staging droplet and verified externally 2026-07-10**: `git pull --ff-only origin main` (clean fast-forward), `scripts/optimusctl.sh update` (rebuild+restart, port binding held at `0.0.0.0:80`), `scripts/optimusctl.sh migrate` (alembic 009→010 applied, confirmed via `alembic current`). External curl checks from outside the droplet confirmed `/health` now reports `square_configured`/`square_environment`, the served `app.js` contains all three new feature markers, and `index.html` contains the Notifications tab. Staging's own `.env` has no Square credentials, so `square_configured: false` there — expected; Square is proven working only against the local dev stack so far.
- [ ] Optional: add Square sandbox credentials to the staging droplet's `.env` + restart if the owner wants Square live on staging too (separate step, not yet done).
- Out of scope: Square live/production, webhooks, email/SMS channels, background jobs.

### Phase 5.6 — Operations Forms Modules & Multi-Role Authorization — IN PROGRESS (sub-phases 0 & 1 complete, uncommitted)

Owner-directed 2026-07-11, planned via `/plan` on branch `agent/claude/landing-page-redesign` (same branch as the Overview dashboard slice above). Source of truth for every module's fields: `/home/dejake/Downloads/Landon_Motor_Works_Operations_Forms.xlsx` (one sheet per module). Replaces the 8 disabled "Coming soon" nav stubs shipped with the Overview dashboard (Service Desk, Diagnostics, Inspections, Scheduling, Technicians, Parts, Vendors, Reports) with real, working modules, one phase at a time — each phase gets its own branch-local commit, gates, and independent review before the next starts, same discipline as Phases 1–4 above.

Owner decisions locked in before planning:
- Technicians get **real logins** (not just data records) — this requires OptimusOS's first genuine multi-role permission system, built first as its own sub-phase since every existing store module currently scopes data by `owner_user_id == auth.user.id` under a strict single-role isolation model.
- Vendors/PurchaseOrders normalized into two related tables (not the spreadsheet's flat one-row-per-PO-with-repeated-vendor-info layout).
- Full roadmap planned now, dependency-ordered; implemented one sub-phase at a time.

Also bundled into this same branch, already done: removed "Talk to Optimus" from the sidebar/mobile nav (chat stays reachable via the Overview "Direct command" panel's quick-prompts, which already `navigate("chat")` — no functionality lost).

**Sub-phases 0 and 1 are implemented, live-verified, and independently + security reviewed (both passed) as of 2026-07-11 — full detail in `docs/context/CURRENT_STATE.md`'s "Phase 5.6 Sub-phase 0 & 1" section. Uncommitted, pending owner approval, same as the rest of this branch.**

**Sub-phase order (dependency-driven):**

1. **Multi-role authorization foundation — DONE 2026-07-11.** New migration adds `UserAccount.shop_owner_id` (nullable self-FK, `NULL` for owners, set to the shop owner's id for technicians) plus a `role IN ('owner','technician')` check constraint. `app/auth.py::effective_owner_id(auth)` (returns `auth.user.id` for an owner, `auth.user.shop_owner_id` for a technician) is now the single scoping call in every store module (`customer_store.py`, `vehicle_store.py`, `estimate_store.py`, `work_order_store.py`, `invoice_store.py`, `payment_store.py`, `notification_store.py`, `customer_history_store.py`, `dashboard_store.py`, `context_store.py`; `square_store.py` needed no direct edit since it inherits scoping transitively through `invoice_store.py`). New `require_role(auth, *allowed)` and `require_owner_context(auth)` route-level gates, applied to all 38 business routes in `app/main.py`. Technician permission boundary for v1 is enforced as fully owner-gated for now (technicians can log in but every business route 403s) since the "own assigned work orders" carve-out needs `WorkOrder.assigned_technician_id`, which is sub-phase 2 scope — see sub-phase 2 below. **Security review pass completed 2026-07-11: PASS, no blocking findings** — full detail in `docs/context/CURRENT_STATE.md`. One hardening item deferred to sub-phase 2's provisioning endpoint (see below), tracked in `docs/context/KNOWN_ISSUES.md`.
2. **Technicians** (`app/technician_store.py`, new `Technician` + `TechnicianTimeEntry` tables, new `WorkOrder.assigned_technician_id` + `WorkOrder.is_comeback` columns). Owner-only CRUD + login provisioning (`POST /api/technicians/{id}/provision-login`); technician self-service clock-in/out. New `#view-technicians` (same list/detail/form pattern as `#view-customers`) plus a simplified `#view-my-day` landing view for technician-role sessions. This sub-phase is also the template CRUD pattern every later sub-phase below reuses without re-describing it. **Provisioning must validate the target `shop_owner_id` references an existing `role="owner"` row before insert** (sub-phase 1's security review finding — see `docs/context/KNOWN_ISSUES.md`). This sub-phase should also carve work orders open for technicians (own-assigned-only, via `require_role`/`effective_owner_id` plus a new assignment check), replacing sub-phase 1's fully-owner-gated interim state.
3. **Parts Inventory + Vendors** (paired). New `Vendor`, `PurchaseOrder` (normalized, per the owner's decision above), `Part`, `PartAllocation` tables. `Part.unit_cost` is the missing wholesale-cost field — once real, `app/dashboard_store.py` gets a follow-up to compute real COGS and finally light up **Gross Profit**, **Gross Profit Margin**, and progress toward **Net Profit** (still needs a general expense concept for full Net Profit; vendor payments are a natural first real expense category). The dashboard follow-up itself is flagged as its own small task after this sub-phase ships, not bundled into it.
4. **Service Desk** (intake). New `ServiceDeskIntake` table with a "convert to estimate" action that pre-fills the existing `create_estimate` flow. Owner-only for v1 (no "service advisor" role exists yet).
5. **Scheduling** (appointments). New `Appointment` table plus a real server-side technician double-booking conflict check (not just a stored field).
6. **Diagnostics + Inspections** (paired). New `DiagnosticRecord` table (reuses the existing `Confidence` enum already used by the estimator) and `Inspection` + `InspectionItem` tables (one inspection visit, many checklist line items — the spreadsheet's flat rows are really this child table). Writable by the assigned technician on their own assigned work order.
7. **Reports.** New `SavedReportRequest` table — per the workbook's own stated purpose, a lightweight recurring-report request/tracking log, not a BI engine. Owner-only. Built last since it conceptually reports on everything above it.

**Required tests per sub-phase:** full CRUD + owner isolation (same pattern as every existing slice); from sub-phase 1 onward, also a cross-*role* isolation sweep (technician session gets `403`/empty on every owner-only route; sees only their own assigned work). Sub-phase 1 additionally reruns the *entire* existing test suite after the mechanical `effective_owner_id` swap, since a missed call site would silently regress an existing cross-user isolation guarantee.

**Verification per sub-phase:** same gate sequence as every slice on this branch — `ruff format`/`ruff check .`, `pyright`, `pytest -q`, `node --check app/static/app.js`, then a live Playwright check against the rebuilt `backend` container (the CSP-enforcing surface) under a synthetic seeded account, deleted afterward. No live OpenAI calls needed for any of this.

**Acceptance (per sub-phase):** backend + frontend + tests + non-billable live proof + docs updated + independent review passed, before the next sub-phase starts — sub-phase 1 additionally requires a security review pass. Nothing committed, pushed, or deployed without separate explicit owner approval, same as every other slice in this roadmap.

- [x] Sub-phase 0 — remove "Talk to Optimus" from nav. (2026-07-11, uncommitted)
- [x] Sub-phase 1 — multi-role authorization foundation + security review. (2026-07-11, uncommitted; security review PASS)
- [ ] Sub-phase 2 — Technicians.
- [ ] Sub-phase 3 — Parts Inventory + Vendors (+ Gross Profit/Net Profit dashboard follow-up).
- [ ] Sub-phase 4 — Service Desk.
- [ ] Sub-phase 5 — Scheduling.
- [ ] Sub-phase 6 — Diagnostics + Inspections.
- [ ] Sub-phase 7 — Reports.

### Phase 6 — Production Readiness
- Threat model (approval links, session cookies, owner auth, public endpoints, PDF generation).
- Focused audits: auth/session, approval tokens (implement the deferred **revoked-token** status here — it graduates from "deferred" to "required"), financial calculations, customer documents.
- Rate limiting re-verified for multi-instance reality (current limiter is in-process memory, single-instance only — document or move to Redis-backed).
- Backup/restore + deployment rollback re-proven on production infrastructure.
- Error monitoring with alerting; a written retention policy for customer data/documents.
- Add OpenAI usage/cost logging before real money flows regularly (gap identified during the Estimate Approval live proofs).
- **Owner-only pilot first** (real jobs, no customer-facing links) → then **controlled customer pilot** (a handful of real approval links, monitored).

## Agent assignments

| Agent | Role |
|---|---|
| Claude | Slice coordinator + implementer-of-record: `/project-sync`, explore → plan → implement → verify via `optimus-*` subagents, runs gates, runtime proofs, docs, `/end-session`. Owns one branch at a time. |
| Codex | Independent reviewer of Claude's diffs from a separate worktree, or implementer of a slice while Claude reviews — never both writing the same worktree at once. Suggested split: Codex on frontend-heavy work (invoice HTML/PDF templates), Claude on store/migration/API work. |
| Fable (or other review-only model) | High-scrutiny review at slice boundaries: architecture drift, financial-integrity logic, exposure/isolation review, release-readiness audits, cross-phase planning. Reviews; does not implement mid-slice. |

## Stop conditions

1. Any gate (ruff/pyright/pytest/build/migration) red → slice halts; max 3 repair attempts per gate, then stop with a root-cause writeup.
2. Cross-user isolation test failing → hard stop for the whole project, not just the slice.
3. Any secret/token/internal-pricing leak found in logs, payloads, or documents → hard stop + security review before further feature work.
4. Estimate Approval validation weakened to ease downstream work → automatic reject in review.
5. Previous slice not fully verified (including independent review) → next slice may not start.
6. Any live OpenAI spend, push, merge, deploy, or destructive DB action without current-turn approval → not performed.
7. Two agents needing write access to one worktree → stop and re-sequence.

## GitHub workflow

- One slice = one branch: `feat/work-orders` → `feat/invoices` → `feat/payment-tracking` → `harden/local-mvp` → `ops/staging`.
- Push at every green verification milestone, not just at slice end.
- Merge to `main` only with explicit approval, only after independent review passes.
- Saved to GitHub: source, migrations, tests, `docs/context/`, scripts, `.env.example`, Compose/nginx config.
- Never saved: `.env`, keys/tokens, logs, proof-run screenshots, DB volumes, cache, one-off proof scripts, real customer data.
