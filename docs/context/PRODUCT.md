# Product

Purpose: verified product scope, users, and current versus not-yet-built modules.
Information owner: Landon Motor Works owners and repository maintainers.
Read when: evaluating workflows, UI scope, or what should be shown to an owner or customer.
Update when: the product scope, supported workflows, or owner approval boundaries change.
Last verified date: 2026-07-22 (operating-mode onboarding facts added and the invoice/payment status labels corrected to match the evidence matrix; the `docs/context/GOAL_EVIDENCE_MATRIX.md` Part A table is the authoritative module inventory, and `docs/context/CURRENT_STATE.md` carries the fuller current state).
Relevant sources: `README.md`, `app/static/index.html`, `app/static/app.js`, `app/control.py`, `docs/frontend-audit.md`, `docs/ui-control-matrix.md`, `app/models.py`, `docs/context/CURRENT_STATE.md`.

## Verified Product Facts

- Intended owner and user: Landon Motor Works owner/operator, with Optimus as the owner-facing management agent.
- OptimusOS currently supports owner sign-in, protected chat, protected location resolution, protected saved estimates, customer approval views, work orders, invoices, health checks, and readiness checks.
- Customer-visible UI currently centers on the command deck, talk-to-Optimus flow, job estimator, and system bay.
- Estimates are itemized and include labor, selected parts, fees, supplies, taxes, warnings, tools, and source links.
- OptimusOS supports three **operating modes** — Solo, Mobile Field, and Shop — as a workflow-shape axis kept separate from subscription tier. An owner deliberately selects a mode after signup through a **non-blocking, owner-only** post-signup onboarding step (Solo / Mobile Field / Shop); existing shops are grandfathered to already-confirmed, and account creation is never blocked on the choice. Navigation is capability-shaped per mode as a UI affordance over the capability service. Capability **enforcement is not shipped** (the Bays capability is observe-only), and switching mode hides nothing permanently and deletes no data.

## Status Labels

- Partially implemented: estimate approval runtime proof, because source and local automated coverage exist but billable live browser proof remains intentionally deferred pending owner approval.
- Implemented: owner login/logout/me, server-side sessions, chat, estimate workflow, estimate approval persistence and UI routes, location resolution, health, readiness, static frontend delivery, customer management, vehicle management, work-order management, invoice management (generation/issue/HTML/PDF), payment tracking (recording/void/schedule/balance derivation), and owner-selected operating modes (Solo / Mobile Field / Shop) with owner-only non-blocking post-signup onboarding and capability-shaped navigation (non-enforcing; Bays observe-only). Invoices and payment tracking are recorded as implemented, migrated, and tested in `docs/context/GOAL_EVIDENCE_MATRIX.md` (Part A, migrations `008` and `009`).
- Planned: observability expansion (Phase 2, next), staging, and production hardening.
- Not approved: any claim that production-hardening modules already exist.

## Current Versus Future

- Current capabilities are the authenticated research and estimate workflows documented in `CURRENT_STATE.md`.
- Roadmap items remain in `ROADMAP.md` until they are actually implemented and verified.
- Do not describe planned modules as existing product functionality.
