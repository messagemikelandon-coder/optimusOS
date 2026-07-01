# Product

Purpose: verified product scope, users, and current versus not-yet-built modules.
Information owner: Landon Motor Works owners and repository maintainers.
Read when: evaluating workflows, UI scope, or what should be shown to an owner or customer.
Update when: the product scope, supported workflows, or owner approval boundaries change.
Last verified date: 2026-07-01.
Relevant sources: `README.md`, `app/static/index.html`, `app/static/app.js`, `app/control.py`, `docs/frontend-audit.md`, `docs/ui-control-matrix.md`, `app/models.py`.

## Verified Product Facts

- Intended owner and user: Landon Motor Works owner/operator, with Optimus as the owner-facing management agent.
- OptimusOS currently supports owner sign-in, protected chat, protected location resolution, protected estimates, health checks, and readiness checks.
- Customer-visible UI currently centers on the command deck, talk-to-Optimus flow, job estimator, and system bay.
- Estimates are itemized and include labor, selected parts, fees, supplies, taxes, warnings, tools, and source links.

## Status Labels

- Implemented: owner login/logout/me, server-side sessions, chat, estimate workflow, location resolution, health, readiness, and static frontend delivery.
- Partially implemented: owner-facing business output and estimate presentation, because the repo documents the flow but not all downstream business records.
- Planned: customer management, vehicle management, work orders, invoice handling, approval queue, observability expansion, staging, and production hardening.
- Not approved: any claim that the repository already contains separate customer, vehicle, work-order, or approval modules.

## Current Versus Future

- Current capabilities are the authenticated research and estimate workflows documented in `CURRENT_STATE.md`.
- Roadmap items remain in `ROADMAP.md` until they are actually implemented and verified.
- Do not describe planned modules as existing product functionality.
