# Plans

Purpose: durable phase checklist for OptimusOS from the verified Estimate Approval slice through to a controlled customer pilot. This is the single "where are we" reference — read it before re-deriving a roadmap.
Information owner: repository maintainers (roadmap authored 2026-07-07).
Read when: starting any new slice, or checking overall project sequencing.
Update when: a phase's acceptance criteria are met, or the sequence changes.
Last verified date: 2026-07-08.
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

### Phase 5 — Private Staging
**Blocked until Phase 4 passes.**

- Separate host/environment; separate PostgreSQL + Redis with distinct credentials; synthetic data only, no real customers.
- Private domain + HTTPS, HSTS, secure cookies flipped on (currently `false` locally — verify it's env-driven).
- Secrets injected from environment/secrets store, never committed.
- Migration strategy as an explicit deploy step with a rehearsed downgrade.
- Backups: nightly `pg_dump`, **restore actually rehearsed once** into a scratch database.
- Monitoring on `/health` + `/ready`, error-log alerting, disk-space alerting.
- Rollback rehearsed once (previous image tag retained).
- Decide *where* staging will live during Phases 1–3, so Phase 5 doesn't stall on unmade infrastructure decisions.

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
