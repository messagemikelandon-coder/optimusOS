# Plans

Purpose: durable phase checklist for OptimusOS from the verified Estimate Approval slice through to a controlled customer pilot. This is the single "where are we" reference — read it before re-deriving a roadmap.
Information owner: repository maintainers (roadmap authored 2026-07-07).
Read when: starting any new slice, or checking overall project sequencing.
Update when: a phase's acceptance criteria are met, or the sequence changes.
Last verified date: 2026-07-13 (all Phase 5.6 sub-phases confirmed merged to `main` via `gh pr list --state merged` and a clean-checkout gate run — 278 tests passing, not carried forward from a prior claim).
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

### Phase 5.6 — Operations Forms Modules & Multi-Role Authorization — CLOSED, all 8 sub-phases merged to `main` (PR #17, #19, #20, #23)

Owner-directed 2026-07-11, planned via `/plan` on branch `agent/claude/landing-page-redesign` (same branch as the Overview dashboard slice above). Source of truth for every module's fields: `/home/dejake/Downloads/Landon_Motor_Works_Operations_Forms.xlsx` (one sheet per module). Replaces the 8 disabled "Coming soon" nav stubs shipped with the Overview dashboard (Service Desk, Diagnostics, Inspections, Scheduling, Technicians, Parts, Vendors, Reports) with real, working modules, one phase at a time — each phase gets its own branch-local commit, gates, and independent review before the next starts, same discipline as Phases 1–4 above.

Owner decisions locked in before planning:
- Technicians get **real logins** (not just data records) — this requires OptimusOS's first genuine multi-role permission system, built first as its own sub-phase since every existing store module currently scopes data by `owner_user_id == auth.user.id` under a strict single-role isolation model.
- Vendors/PurchaseOrders normalized into two related tables (not the spreadsheet's flat one-row-per-PO-with-repeated-vendor-info layout).
- Full roadmap planned now, dependency-ordered; implemented one sub-phase at a time.

Also bundled into this same branch, already done: removed "Talk to Optimus" from the sidebar/mobile nav (chat stays reachable via the Overview "Direct command" panel's quick-prompts, which already `navigate("chat")` — no functionality lost).

**Sub-phases 0, 1, and 2 are implemented, live-verified, and independently + security reviewed (all passed) as of 2026-07-11 — full detail in `docs/context/CURRENT_STATE.md`'s "Phase 5.6 Sub-phase 0 & 1" and "Phase 5.6 Sub-phase 2" sections. Merged to `main` via PR #17.**

**Sub-phases 3, 4, 6, and 7 were built 2026-07-13 on `agent/claude/shop-management-ui`, each with real disclosed deviations from this plan's original scope (Purchase Orders not built, technician write-access not built, normalized `InspectionItem`/`Confidence`-enum reuse not built, `SavedReportRequest` tracking log not built — see each numbered entry below and `docs/context/CURRENT_STATE.md`'s "Phase 5.6 Sub-phases 3, 4, 6, 7" section for exactly what shipped instead). Independent review passed (one real bug found and fixed same-session); no dedicated `optimus-security-reviewer` pass has been run on these four sub-phases specifically, unlike sub-phases 1-2 and 5. **Merged to `main` via PR #20 (2026-07-13).**

**Sub-phase 5 (Scheduling) was built 2026-07-13, same branch, in a separate session from sub-phases 3/4/6/7.** Full `Appointment`/`Bay`/`WorkingHours`/`ScheduleBlock` data model, availability/conflict engine (technician overlap, bay overlap, configurable travel buffer, DST-aware America/Chicago working-hours enforcement, schedule-block conflicts), all 7 specified appointment endpoints plus `GET /api/availability`, full CRUD for schedule blocks (as specified) and — a disclosed scope addition beyond the literal spec, since otherwise the feature would be unconfigurable — full CRUD for bays and working hours too (the spec only asked for read endpoints on those). Day/week agenda-style calendar UI (not a pixel-positioned grid — a deliberate simplification, matching the spec's allowance for a move/reschedule dialog instead of drag-and-drop). 23 tests including a DST-crossing test that asserts real UTC-hour differences between winter/summer local appointment times. Independent review found and both bugs were fixed same-session: (1) a `ScheduleBlock` could be created with both `technician_id` and `bay_id` set, which the conflict engine treated as OR/broader-than-intended — now rejected at the model layer (a block targets a technician or a bay, not both); (2) the backend didn't block canceling a `completed` appointment even though the frontend hid that button — now enforced server-side too. Security review: **PASS, no findings.** Full detail in `docs/context/CURRENT_STATE.md`'s "Phase 5.6 Sub-phase 5" section.

**Sub-phase order (dependency-driven):**

1. **Multi-role authorization foundation — DONE 2026-07-11.** New migration adds `UserAccount.shop_owner_id` (nullable self-FK, `NULL` for owners, set to the shop owner's id for technicians) plus a `role IN ('owner','technician')` check constraint. `app/auth.py::effective_owner_id(auth)` (returns `auth.user.id` for an owner, `auth.user.shop_owner_id` for a technician) is now the single scoping call in every store module (`customer_store.py`, `vehicle_store.py`, `estimate_store.py`, `work_order_store.py`, `invoice_store.py`, `payment_store.py`, `notification_store.py`, `customer_history_store.py`, `dashboard_store.py`, `context_store.py`; `square_store.py` needed no direct edit since it inherits scoping transitively through `invoice_store.py`). New `require_role(auth, *allowed)` and `require_owner_context(auth)` route-level gates, applied to all 38 business routes in `app/main.py`. Technician permission boundary for v1 is enforced as fully owner-gated for now (technicians can log in but every business route 403s) since the "own assigned work orders" carve-out needs `WorkOrder.assigned_technician_id`, which is sub-phase 2 scope — see sub-phase 2 below. **Security review pass completed 2026-07-11: PASS, no blocking findings** — full detail in `docs/context/CURRENT_STATE.md`. One hardening item deferred to sub-phase 2's provisioning endpoint (see below), tracked in `docs/context/KNOWN_ISSUES.md`.
2. **Technicians — DONE 2026-07-11.** `app/technician_store.py`, new `Technician` + `TechnicianTimeEntry` tables (the latter with a DB-level partial unique index enforcing at most one open clock-in per technician), new `WorkOrder.assigned_technician_id` + `WorkOrder.is_comeback` columns. Owner-only CRUD + login provisioning (`POST /api/technicians/{id}/provision-login`, which re-validates the sub-phase-1-mandated `shop_owner_id`-resolves-to-a-real-owner check as defense-in-depth); technician self-service clock-in/out (`POST /api/technicians/me/clock-in|out`) and own-profile view (`GET /api/technicians/me`, deliberately excludes the owner-only `hourly_cost` wage field via a dedicated `TechnicianSelfRead` model — a security-review finding, fixed same-day). New `#view-technicians` (list/detail/form, same pattern as `#view-customers` — this sub-phase is the template CRUD pattern every later sub-phase below reuses without re-describing it) plus `#view-my-day` for technician-role sessions, with role-based nav visibility (`data-owner-only`/`data-technician-only` + `applyRoleNavVisibility()`) and role-based post-login/reload routing. Work orders carved open for technicians (own-assigned-only): `GET /api/work-orders`, `GET /api/work-orders/{id}`, `POST /api/work-orders/{id}/status`, `POST /api/work-orders/{id}/notes` now use a new `OwnerOrTechnicianAuthContextDep`, scoped in `work_order_store._work_order_query(db, auth)` via the technician's own linked `Technician.id`; a new owner-only `POST /api/work-orders/{id}/assign-technician` route lets the owner assign/unassign. **Independent + security review both PASS 2026-07-11**, two real findings fixed same-day (see `docs/context/CURRENT_STATE.md`'s "Phase 5.6 Sub-phase 2" section for full detail): a technician losing their My Day landing on page reload (frontend routing bug), and `hourly_cost` leaking into the technician's own `/api/technicians/me` response (now excluded).
3. **Parts Inventory + Vendors** (paired) — **PARTIALLY DONE, merged to `main` via PR #20.** Built: `Vendor` and `Part` tables (owner-scoped CRUD, `Part.vendor_id` nullable FK), `Part.unit_cost`/`unit_price` fields exist but the dashboard COGS follow-up described below was **not** started. **Deviation from this plan as originally written:** `PurchaseOrder` and `PartAllocation` were not built — this delivered a vendor directory + parts inventory with a reorder-threshold flag, not a purchase-order lifecycle. Full detail in `docs/context/CURRENT_STATE.md`'s "Phase 5.6 Sub-phases 3-5" section.
4. **Service Desk** (intake) — **PARTIALLY DONE, merged to `main` via PR #20.** Built: `IntakeRequest` table + a "convert" action, owner-only. **Deviation from this plan as originally written:** the convert action creates a `Customer` (+ optional `Vehicle` if make/model were supplied) via the existing customer/vehicle store functions, not a pre-filled `create_estimate` call — an owner still has to open the Job Estimator separately afterward. No `ServiceDeskIntake` table name was used (named `IntakeRequest` instead, tracked in `intake_requests`).
5. **Scheduling** (appointments) — **DONE 2026-07-13, same branch.** `Appointment`, `Bay`, `WorkingHours`, `ScheduleBlock` tables (migration `016_scheduling`); `app/scheduling_store.py` conflict engine covering technician overlap, bay overlap, travel buffer, working hours (DST-aware, skipped if a technician has zero configured hours), and schedule blocks; owner-only routes for appointments (list/get/create/patch/move/cancel), availability, schedule blocks, plus bay/working-hours CRUD (a disclosed scope addition beyond the literal endpoint list, needed to make bays/hours configurable at all). Day/week agenda-style frontend (list+detail+form pattern, not a pixel-grid). See sub-phase-5 addendum above for the two bugs an independent review found and fixed.
6. **Diagnostics + Inspections** (paired) — **PARTIALLY DONE, merged to `main` via PR #20.** Built: `DiagnosticFinding` and `Inspection` tables, owner-only CRUD (hard delete, not soft-archive — a deliberate deviation from every other module's convention, see `CURRENT_STATE.md`). **Deviations from this plan as originally written:** (1) not writable by the assigned technician on their own work order — both modules are strictly owner-gated (`OwnerAuthContextDep`), no `OwnerOrTechnicianAuthContextDep` carve-out was added; (2) `DiagnosticFinding` does not reuse the estimator's existing `Confidence` enum; (3) `Inspection` checklist items are stored as a JSON column on the `inspections` row rather than a normalized `InspectionItem` child table.
7. **Reports.** — **PARTIALLY DONE, merged to `main` via PR #20.** Built: a read-only Reports view presenting revenue/work-order/invoice-status/balance summaries sourced from the existing `/api/dashboard/summary` and `/api/invoices` endpoints — no new backend endpoint or table. **Deviation from this plan as originally written:** no `SavedReportRequest` table — this is a live dashboard-style view, not the recurring-report request/tracking log the plan described. Payment activity, technician time, and commission reports are explicitly out (documented in the view itself as needing new backend aggregation endpoints that don't exist).

**Required tests per sub-phase:** full CRUD + owner isolation (same pattern as every existing slice); from sub-phase 1 onward, also a cross-*role* isolation sweep (technician session gets `403`/empty on every owner-only route; sees only their own assigned work). Sub-phase 1 additionally reruns the *entire* existing test suite after the mechanical `effective_owner_id` swap, since a missed call site would silently regress an existing cross-user isolation guarantee.

**Verification per sub-phase:** same gate sequence as every slice on this branch — `ruff format`/`ruff check .`, `pyright`, `pytest -q`, `node --check app/static/app.js`, then a live Playwright check against the rebuilt `backend` container (the CSP-enforcing surface) under a synthetic seeded account, deleted afterward. No live OpenAI calls needed for any of this.

**Acceptance (per sub-phase):** backend + frontend + tests + non-billable live proof + docs updated + independent review passed, before the next sub-phase starts — sub-phase 1 additionally requires a security review pass. Nothing committed, pushed, or deployed without separate explicit owner approval, same as every other slice in this roadmap.

- [x] Sub-phase 0 — remove "Talk to Optimus" from nav. (2026-07-11, merged via PR #17)
- [x] Sub-phase 1 — multi-role authorization foundation + security review. (2026-07-11, merged via PR #17; security review PASS)
- [x] Sub-phase 2 — Technicians. (2026-07-11, merged via PR #17; independent + security review PASS, 2 findings fixed same-day)
- [x] Sub-phase 3 — Parts Inventory + Vendors. (2026-07-13, merged via PR #20; Purchase Orders/Gross-Profit-dashboard follow-up not built — now tracked as Phase 6 Part D below)
- [x] Sub-phase 4 — Service Desk. (2026-07-13, merged via PR #20)
- [x] Sub-phase 5 — Scheduling. (2026-07-13, merged via PR #23; independent + security review PASS, 2 findings fixed same-day)
- [x] Sub-phase 6 — Diagnostics + Inspections. (2026-07-13, merged via PR #20; hard-delete/no-technician-access deviations now tracked as Phase 6 Parts C/E below)
- [x] Sub-phase 7 — Reports. (2026-07-13, merged via PR #20; full reporting buildout now tracked as Phase 6 Part G below)

### Phase 6 — Production Readiness

Owner-directed expansion (2026-07-13): with Phase 5.6 closed, work continues toward a stable, production-ready platform. **Scheduling is explicitly out of scope for every part below** — do not build, redesign, replace, or modify it; only avoid breaking its existing integration points. Each part below ships as its own branch/PR with the standard gate sequence (`ruff format --check`, `ruff check`, `pyright`, `pytest`, `node --check`, plus Alembic upgrade/downgrade and Docker build checks where migrations or images are touched) and an independent review before merge, same discipline as every phase above. Nothing is committed, pushed, merged, or deployed without explicit current-turn owner approval; no billable OpenAI calls without separate explicit approval for that exact run.

**Part A — CI enforcement. DONE, merged to `main`.** Replaced the previously handoff-only GitHub Actions setup (`.github/workflows/ai-coordination.yml` only validated the AI handoff doc — confirmed 2026-07-13, no test/lint/build gate ran in CI before this) with a new `.github/workflows/ci.yml`, three jobs on every PR and push to `main`: (1) `lint-typecheck-test` — `ruff format --check`, `ruff check`, `pyright`, `pytest`, `node --check app/static/app.js`, `git diff --check` against the PR base; (2) `migrations` — a real Postgres 16 service container, confirms a single linear Alembic head, upgrades from a clean database, then a downgrade/upgrade round-trip; (3) `docker-compose-integration` — validates `docker compose config -q` for both the base and staging-overlay compose files (placeholder `.env.example` values only, output always suppressed with `-q` so nothing resolved is ever printed), builds the backend/worker image via `docker compose build backend worker`, boots the full stack, polls `/health`+`/ready`, applies migrations inside the running container, and runs the existing `scripts/scan_logs_for_secrets.py` against all four services' logs. Every command in every job was hand-validated against real local Docker/Postgres containers before being committed to the workflow file, not just written from the spec. **Branch protection is not enabled on `main`** — confirmed via `gh api repos/.../branches/main/protection` returning `404 Branch not protected` on 2026-07-13. Recommendation, not yet actioned (repo-settings changes need separate explicit owner approval): require the `lint-typecheck-test`, `migrations`, and `docker-compose-integration` status checks before merge, require PRs before pushing to `main`, and consider requiring at least one approval once more than one human/agent regularly pushes here.

**Part B — Synthetic test-account provisioning. DONE, merged to `main`.** A test-only path to mint synthetic owner/technician accounts for automated and local E2E use. New migration `017_synthetic_test_accounts` (`user_accounts.is_synthetic_test_account`, indexed) + `app/test_support_store.py` + four new `/api/test-support/*` routes (`POST synthetic-owner`, `POST synthetic-technician`, `DELETE synthetic-accounts/{id}`, `DELETE synthetic-accounts` sweep). Double-gated — both `OPTIMUS_TEST_ACCOUNT_PROVISIONING=true` *and* a non-`"production"` `app_env` are independently required (neither alone is sufficient); every route returns a bare `404` when disabled rather than a `403`, so the routes don't reveal they exist in any real deployment that hasn't explicitly opted in (off by default everywhere, including local dev and CI). Random credentials (`secrets.token_urlsafe`), never the real owner's, reused via the existing `technician_store.create_technician`/`provision_login` functions rather than reimplementing technician creation. Cleanup refuses to delete anything not flagged `is_synthetic_test_account` (can never delete a real account, even by guessing/iterating ids) and explicitly deletes any linked technician row rather than relying solely on the database's `ON DELETE CASCADE` — see the SQLite-vs-Postgres FK-enforcement gap this surfaced, in `docs/context/KNOWN_ISSUES.md`. Verified: 8 new tests in `tests/test_test_support_api.py` (disabled-by-default, disabled-in-production, real owner provisioning + real login, real technician provisioning + real login, rejects attaching to a non-synthetic owner, per-account cleanup + cascade, refuses to delete a real account, sweep cleanup) plus a live proof against a real Postgres container over real HTTP (provision owner → provision technician → real `/api/auth/login` as both → delete owner → confirm both rows gone from Postgres → sweep-cleanup two more owners → confirm zero rows). Alembic upgrade/downgrade round-tripped against real Postgres. This directly closes the gap every Phase 5.6 sub-phase's handoff has flagged: *no real authenticated end-to-end browser proof exists for any Phase 5.6 module* — every "live Playwright proof" so far used a client-side `state.auth.authenticated = true` bypass against an unauthenticated session, not a real login. Part C can now use this for real logins instead.

**Part C — Authenticated Playwright E2E suite.** Permanent tests (not one-off proofs) using Part B's real synthetic accounts and real API calls, no frontend-state bypass: the full repair workflow (customer → vehicle → estimate → approval → work order → technician assignment → status walk → completion → invoice → payment → balance/status), the Phase 5.6 modules (vendor/part/reorder, Service Desk intake→conversion, diagnostic finding, inspection, technician My Day/clock-in-out/isolation), Reports against real seeded values, and security behavior (401s, cross-role/cross-owner denial, no CSP violations, no unexpected console errors, no internal cost/margin in customer-facing documents).

**Part D — Diagnostics/Inspections auditability.** These two tables currently use hard delete (a disclosed deviation from every other module's soft-archive convention — see `docs/context/KNOWN_ISSUES.md`). Replace with archive/void + who-created/modified/archived + timestamps + an append-only revision/audit-event log, migrated without data loss. Owners see archived records; technicians (once Part E lands) see only records tied to their own assigned work orders; customer-facing output excludes internal-only notes.

**Part E — Technician workflow for Diagnostics/Inspections.** Both modules are currently strictly `OwnerAuthContextDep`-gated with no technician carve-out (a disclosed Phase 5.6 deviation). Add read/write access scoped to the technician's own assigned work orders (enforced at both the route dependency and the store query, same pattern as `work_order_store.py`'s existing technician carve-out — do not rely on the FK alone), excluding supplier cost/internal labor cost/margin/owner notes/other-technician wage data from technician-facing responses. Cross-role and cross-owner tests for every write path.

**Part F — Parts/Vendors: purchase-order + allocation workflow.** Sub-phase 3 shipped a vendor directory + parts inventory with a reorder-threshold flag, but explicitly not the `PurchaseOrder`/`PartAllocation` lifecycle originally planned (draft→submitted→partially-received→received→cancelled, line items, partial/full receiving with duplicate-receipt protection and append-only receipt history, work-order part allocation with quantity-required/allocated/used/returned and inventory deduction/return). Supplier cost and markup must never reach customer-facing estimates/invoices/approval pages/PDFs — only the final customer parts price. Decimal money, transaction-safe inventory updates, no negative inventory without an explicit recorded override policy. Once reliable, wire real parts cost into the dashboard's currently-honest "not available" Gross Profit/Net Profit/Gross Margin metrics — don't display them until the underlying cost data is actually complete.

**Part G — Reports completion.** Sub-phase 7 shipped a read-only view reusing the existing dashboard/invoice aggregation endpoints (no `SavedReportRequest` table, no new backend aggregation) — explicitly missing payment-activity, technician-time, and commission reports (documented honestly in the view itself). Build server-side aggregation endpoints for the full report set (revenue/labor/parts-cost/gross-profit/margin/AR/payments/overdue/cycle-time/technician billed-vs-clocked hours/efficiency/comeback rate/diagnostic+inspection findings/parts usage/inventory valuation/low-stock/vendor purchasing), owner-scoped, date-filtered, paginated where needed, CSV export, honest unavailable states where supporting data (e.g. Part F's cost data) isn't there yet. Report scheduling/delivery stays a separate future phase.

**Part H — Security/production hardening.** Threat model (approval links, session cookies, owner/technician auth, public endpoints, PDF generation, Square integration, file/document exposure, cross-tenant access); approval-token revocation (graduates from deferred to required); rate limiting re-verified for multi-instance reality (current limiter is in-process memory, single-instance only); structured security event logging; OpenAI usage/cost logging before real money flows regularly; customer-data retention policy, export process, and deletion process (with required financial-record retention exceptions); backup verification + restore rehearsal + deployment rollback re-proven on production infrastructure; monitoring requirements for health/readiness/errors/disk-space/database. Don't claim monitoring is active unless actually configured and verified.

**Part I — Staging verification.** Before any deploy: full gate suite, Docker builds, clean-DB migration check, the Part C authenticated Playwright run, a log secret scan, customer-facing HTML/PDF verification, and confirmation no Scheduling code was touched. Produce an exact deployment checklist (backup, pull/deploy exact commit, build, migrate, restart, health check, readiness check, authenticated smoke test, rollback condition, rollback command, post-deploy monitoring). As of 2026-07-13, staging is confirmed running a commit after PR #21 but before PR #22/#23 (see `docs/context/CURRENT_STATE.md`'s Staging Prep section) — the immediate, much smaller, separate task of catching the droplet up to current `main` does not require any of Parts A-H and can happen independently once approved.
- **Owner-only pilot first** (real jobs, no customer-facing links) → then **controlled customer pilot** (a handful of real approval links, monitored) — after Parts A-I above.

- [x] Part A — CI enforcement. (2026-07-13, merged; branch-protection recommended but not enabled — needs separate owner approval)
- [x] Part B — Synthetic test-account provisioning. (2026-07-13, merged; live-verified against real Postgres over real HTTP)
- [ ] Part C — Authenticated Playwright E2E suite.
- [ ] Part D — Diagnostics/Inspections auditability (archive/void + audit trail).
- [ ] Part E — Technician workflow for Diagnostics/Inspections.
- [ ] Part F — Parts/Vendors purchase-order + allocation workflow.
- [ ] Part G — Reports completion.
- [ ] Part H — Security/production hardening.
- [ ] Part I — Staging verification + deployment checklist.
- [ ] Owner-only pilot, then controlled customer pilot.

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
