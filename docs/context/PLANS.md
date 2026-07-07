# Plans

Purpose: durable phase checklist for OptimusOS from the verified Estimate Approval slice through to a controlled customer pilot. This is the single "where are we" reference — read it before re-deriving a roadmap.
Information owner: repository maintainers (roadmap authored 2026-07-07).
Read when: starting any new slice, or checking overall project sequencing.
Update when: a phase's acceptance criteria are met, or the sequence changes.
Last verified date: 2026-07-07.
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
- [ ] `AGENTS.md` / AI Coordination Pack: `AGENTS.md` itself committed (`c46d53f` "docs: update agent operating rules", by Codex) but **not yet pushed**, and the rest of the pack (`.claude/`, `.github/`, `CLAUDE.md`, `docs/context/AI_WORKFLOW.md`, `scripts/ai_context_snapshot.sh`, `scripts/check_ai_handoff.py`) remains **untracked**. Needs an explicit decision: commit the remainder as its own clearly-labeled commit, or leave untracked permanently.
- [ ] Push `c46d53f` (or whatever HEAD is after the decision above) and reconfirm `origin` hash == local HEAD.
- [ ] `SESSION_HANDOFF.md` reflects the pushed state.

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

**Acceptance:** all 8 test categories pass; PDF text-extraction test asserts forbidden fields never appear; idempotent completion; restart persistence; reviews pass; docs updated.

### Phase 3 — Payment Tracking
**Goal:** track invoice payments, deposits, installments, balances, and overdue state without live payment processing.

Branch: `feat/payment-tracking`.

- Migration `009_payments`: `invoice_payments` (append-only — amount, method label, recorded_at, note, `voided_by_payment_id` for reversals; **no card/bank fields in the schema at all**, so there is nothing to leak), `payment_schedules` (installments for the two-month plan).
- Balance = server-side Decimal sum over non-voided payments; invoice status derived server-side, never client-supplied.
- Overdue computed against `due_at` with an injectable clock so tests don't sleep or fake system time.
- Overpayment: reject by default (explicit, tested); corrections go through void + re-record, never delete.
- Recording a deposit payment satisfies the linked work order's `deposit_received` prerequisite.

Required tests: full payment; partial payment; deposit; installments; overpayment rejection; void/reversal; invoice status updates; overdue calculation; cross-user isolation; restart persistence. Plus Decimal-precision regression tests — no float arithmetic anywhere in money paths.

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
