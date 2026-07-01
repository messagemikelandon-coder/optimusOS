# Business Rules

Purpose: verified owner and customer workflow rules for Landon Motor Works.
Information owner: Landon Motor Works owner and repository maintainers.
Read when: changing user-facing copy, estimate logic, approval logic, or workflow scope.
Update when: an owner rule changes or new business evidence is added.
Last verified date: 2026-07-01.
Relevant sources: `app/static/index.html`, `app/static/app.js`, `app/control.py`, `app/security.py`, `docs/frontend-audit.md`, `docs/ui-control-matrix.md`, `README.md`.

## Verified Rules

- Optimus is owner-facing.
- Owner authentication is required before protected chat, estimate, and location workflows.
- Estimates are itemized and include labor, parts, fees, supplies, taxes, warnings, tools, and source links.
- Parts prices are treated as evidence-based data; hidden prices are not invented.
- When a retailer hides price or inventory, the workflow should still provide the official product or search link if available.
- Public-facing UI should not expose server API keys or other sensitive internal credentials.
- Current-turn confirmation is required for money movement, destructive actions, or other explicitly protected actions.

## Customer-Facing Output Rules

- Customer-facing output should distinguish between verified price evidence and missing evidence.
- Internal approval logic and research notes should not be presented as customer promises.
- If a rule is not supported by repository evidence, do not promote it to a verified business rule.

## Owner Review Required

- Payment options are not fully documented in the repository evidence.
- Deposit requirements are not fully documented in the repository evidence.
- Conditions under which work may begin are only partially documented through approval policy and should be confirmed by the owner.
- Customer-data handling beyond current auth and privacy boundaries is not yet fully documented.
