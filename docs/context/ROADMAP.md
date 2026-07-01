# Roadmap

Purpose: ordered delivery phases for the repository.
Information owner: repository maintainers and owners who approve work scope.
Read when: deciding what to build next or what remains out of scope.
Update when: a phase starts, completes, or is intentionally deferred.
Last verified date: 2026-07-01.
Relevant sources: `docs/frontend-audit.md`, `docs/ui-control-matrix.md`, `docs/UI_CONNECTION_AUDIT.md`, `README.md`, `app/main.py`, `app/static/index.html`, `git log --oneline`.

## Phases

| Phase | Objective | Prerequisites | Acceptance criteria | Out of scope | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Authentication completion | Finish owner sign-in, session persistence, and logout behavior. | Auth migration and server-side session model. | Login, `/api/auth/me`, logout, and expiry handling all work and are tested. | Customer, vehicle, and work-order modules. | Complete |
| 2. Existing protected-flow verification | Prove the current protected workflows keep working. | Phase 1. | Login, chat, estimate, location, health, and readiness pass in source and live checks. | New business modules. | Complete |
| 3. Context-management system | Maintain durable project context. | Repository docs and routing guidance. | `docs/context/` exists, root `AGENTS.md` routes correctly, and handoff rules are documented. | Product expansion. | Complete after this commit |
| 4. Frontend component and design system | Build a reusable design system for the current static UI. | Stable protected flows. | Shared frontend primitives and control patterns exist and are verified. | Futuristic redesign experiments. | Planned |
| 5. Futuristic UX redesign | Explore a new visual direction. | Stable design-system baseline. | Approved redesign assets and implementation plan exist. | Backend behavior changes. | Planned |
| 6. Customers | Add customer records and workflows. | Business rules and approved data model. | Customer CRUD and related UI/API flows are implemented and tested. | Vehicle or work-order logic beyond dependencies. | Planned |
| 7. Vehicles | Add vehicle records and workflows. | Customer foundation and approved schema. | Vehicle CRUD and linkage to owners/customers are implemented and tested. | Repair-order and invoicing details. | Planned |
| 8. Work orders | Add work-order lifecycle workflows. | Customer and vehicle data model. | Work-order creation, updates, and status transitions are implemented and tested. | Unapproved billing automation. | Planned |
| 9. Estimates and invoices | Expand estimate and invoice lifecycle. | Work-order workflow. | Estimate and invoice generation, presentation, and record handling are implemented and tested. | Payment processing details not yet approved. | Planned |
| 10. Approval queue | Add explicit approval handling. | Business rules and workflow states. | Approval requests, decisions, and audit trails are implemented and tested. | Silent bypasses. | Planned |
| 11. Observability | Add logs, metrics, and traceability. | Stable request flows. | Operational signals are documented and verified without leaking secrets. | Customer-facing UI redesign. | Planned |
| 12. Security hardening | Tighten auth, secrets, and deployment controls. | Stable auth and deployment baseline. | Security checks and abuse-resistant behaviors pass documented verification. | Product expansion. | Planned |
| 13. Staging | Add a non-production staging target. | Deployment and data-handling decisions. | Staging deployment exists with documented promotion flow. | Public release. | Planned |
| 14. Production | Publish a production deployment path. | Approved security, staging, and owner sign-off. | Production deployment, rollback, and support procedures are documented and verified. | Unapproved changes. | Planned |

## Notes

- Keep phase status aligned with verified evidence, not aspiration.
- If a phase becomes blocked or superseded, mark it clearly rather than implying progress.
