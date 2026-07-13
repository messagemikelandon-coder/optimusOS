# Product

Purpose: verified product scope, users, and current versus not-yet-built modules.
Information owner: Landon Motor Works owners and repository maintainers.
Read when: evaluating workflows, UI scope, or what should be shown to an owner or customer.
Update when: the product scope, supported workflows, or owner approval boundaries change.
Last verified date: 2026-07-08.
Relevant sources: `README.md`, `app/static/index.html`, `app/static/app.js`, `app/control.py`, `docs/frontend-audit.md`, `docs/ui-control-matrix.md`, `app/models.py`, `docs/context/CURRENT_STATE.md`.

## Verified Product Facts

- Intended owner and user: Landon Motor Works owner/operator, with Optimus as the owner-facing management agent.
- OptimusOS currently supports owner sign-in, protected chat, protected location resolution, protected saved estimates, customer approval views, work orders, invoices, health checks, and readiness checks.
- Customer-visible UI currently centers on the command deck, talk-to-Optimus flow, job estimator, and system bay.
- Estimates are itemized and include labor, selected parts, fees, supplies, taxes, warnings, tools, and source links.

## Status Labels

- Partially implemented: estimate approval runtime proof, because source and local automated coverage exist but billable live browser proof remains intentionally deferred pending owner approval.
- Implemented: owner login/logout/me, server-side sessions, chat, estimate workflow, estimate approval persistence and UI routes, location resolution, health, readiness, static frontend delivery, customer management, vehicle management, and work-order management.
- Partially implemented: invoice handling, because source, automated verification, Docker verification, and non-billable live proof now exist, but the Phase 2 independent review gate is still pending.
- Planned: payment tracking, observability expansion, staging, and production hardening.
- Not approved: any claim that payment tracking or production-hardening modules already exist.

## Current Versus Future

- Current capabilities are the authenticated research and estimate workflows documented in `CURRENT_STATE.md`.
- Roadmap items remain in `ROADMAP.md` until they are actually implemented and verified.
- Do not describe planned modules as existing product functionality.
