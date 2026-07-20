# Decisions

Purpose: lightweight architecture decision record for verified repository choices.
Information owner: repository maintainers and owners approving architectural direction.
Read when: changing architecture, auth, deployment, or data flow.
Update when: a decision is made, superseded, or explicitly revisited.
Last verified date: 2026-07-19.
Relevant sources: `git show 060ab68 --stat --summary`, `app/main.py`, `app/auth.py`, `app/config.py`, `app/services/openai_web.py`, `app/services/optimus_chat.py`, `docker-compose.yml`, `ops/nginx/default.conf`, `alembic/versions/002_authentication_tables.py`.

## ADR-001

- ID: ADR-001
- Date: 2026-07-01
- Status: Accepted
- Context: The repository is centered on a FastAPI backend and already ships authenticated API routes.
- Decision: Retain FastAPI as the backend until an approved architecture decision changes it.
- Alternatives considered: replacing the backend stack or introducing a second server framework.
- Consequences: routing, tests, and docs should continue to treat FastAPI as the current backend.
- Files affected: `app/main.py`, `app/auth.py`, `app/config.py`, `tests/test_api.py`.
- Revisit if: an approved migration plan replaces the current backend framework.

## ADR-002

- ID: ADR-002
- Date: 2026-07-01
- Status: Accepted
- Context: Chat and research features use OpenAI and web lookup from the server side.
- Decision: Keep the OpenAI gateway on the server, not in the browser.
- Alternatives considered: browser-side API calls or exposing API keys to client code.
- Consequences: browser code must never receive server API keys.
- Files affected: `app/services/openai_web.py`, `app/services/optimus_chat.py`, `app/main.py`.
- Revisit if: a new approved security design changes the trust boundary.

## ADR-003

- ID: ADR-003
- Date: 2026-07-01
- Status: Accepted
- Context: The frontend currently fetches API paths from the same origin through Nginx.
- Decision: Keep same-origin frontend API calls using `/api/...`.
- Alternatives considered: cross-origin browser API calls or direct backend calls from client code.
- Consequences: the Nginx proxy remains part of the local browser path.
- Files affected: `ops/nginx/default.conf`, `app/static/app.js`, `app/main.py`.
- Revisit if: a new approved frontend deployment topology changes the origin model.

## ADR-004

- ID: ADR-004
- Date: 2026-07-01
- Status: Accepted
- Context: Authentication is already implemented as server-side sessions.
- Decision: Use HttpOnly cookie authentication for browser sessions.
- Alternatives considered: browser-stored bearer tokens or localStorage-based auth.
- Consequences: browser JavaScript cannot read the auth cookie.
- Files affected: `app/auth.py`, `app/main.py`, `tests/test_auth.py`, `app/static/index.html`.
- Revisit if: an approved auth redesign replaces cookie-backed sessions.

## ADR-005

- ID: ADR-005
- Date: 2026-07-01
- Status: Accepted
- Context: Auth tables were added to the database.
- Decision: Store users and sessions in PostgreSQL.
- Alternatives considered: SQLite-only auth persistence or file-based state.
- Consequences: Alembic migrations must remain the source of truth for schema changes.
- Files affected: `alembic/versions/002_authentication_tables.py`, `app/db_models.py`, `app/auth.py`.
- Revisit if: an approved storage redesign changes the persistence layer.

## ADR-006

- ID: ADR-006
- Date: 2026-07-01
- Status: Accepted
- Context: Owner passwords must not be stored in plaintext.
- Decision: Hash passwords with Argon2.
- Alternatives considered: plaintext passwords or weaker hashing.
- Consequences: password verification stays server-side and tests should cover it.
- Files affected: `app/auth.py`, `tests/test_auth.py`, `tests/test_security.py`.
- Revisit if: an approved security review mandates a different password hashing standard.

## ADR-007

- ID: ADR-007
- Date: 2026-07-01
- Status: Accepted
- Context: Browser sessions are stored in a database table.
- Decision: Hash session tokens before storing them.
- Alternatives considered: raw token storage or bearer-token persistence in the browser.
- Consequences: the database does not contain reusable raw session tokens.
- Files affected: `app/auth.py`, `app/db_models.py`, `tests/test_auth.py`.
- Revisit if: an approved auth redesign changes token storage semantics.

## ADR-008

- ID: ADR-008
- Date: 2026-07-01
- Status: Accepted
- Context: Local development and deployment are already orchestrated through Compose.
- Decision: Use Docker Compose for the current deployment stage.
- Alternatives considered: ad hoc process management or a Kubernetes stack.
- Consequences: startup, health, and readiness commands should keep referencing Compose.
- Files affected: `docker-compose.yml`, `scripts/optimusctl.sh`, `docs/UBUNTU_DEPLOYMENT_REPORT.md`.
- Revisit if: an approved deployment plan introduces a different stage target.

## ADR-009

- ID: ADR-009
- Date: 2026-07-01
- Status: Accepted
- Context: There is no approved Kubernetes deployment in the repository.
- Decision: Do not introduce Kubernetes at the current stage.
- Alternatives considered: Kubernetes manifests or cluster orchestration.
- Consequences: deployment docs should stay aligned with Compose and local stack usage.
- Files affected: `docker-compose.yml`, `docs/context/ARCHITECTURE.md`, `docs/context/CURRENT_STATE.md`.
- Revisit if: a production deployment decision explicitly adopts Kubernetes.

## ADR-010

- ID: ADR-010
- Date: 2026-07-01
- Status: Accepted
- Context: The repository contains generated `dist/` artifacts from packaged builds.
- Decision: Do not edit generated dist files directly.
- Alternatives considered: patching generated bundles in place.
- Consequences: source changes must land in real source files and then be regenerated.
- Files affected: `dist/`, `app/`, `docs/`.
- Revisit if: a future packaging workflow changes the generated-artifact policy.

## ADR-011

- ID: ADR-011
- Date: 2026-07-09
- Status: Accepted
- Context: Phase 5 (Private Staging) requires a separate host/environment; the roadmap explicitly calls for deciding where staging will live before Phase 5 stalls on unmade infrastructure decisions. This is a real-money, real-credentials decision that requires the owner's direct choice, not an autonomous one.
- Decision: Staging will be hosted on a DigitalOcean droplet (recommended over Hetzner Cloud for setup simplicity/documentation quality at a small cost premium), with the domain registered through Cloudflare (at-cost registration, and Cloudflare's free proxy/DNS will terminate HTTPS at the edge, satisfying the HTTPS/HSTS requirement without self-managed TLS certificates).
- Alternatives considered: Hetzner Cloud (cheaper, stricter signup, less beginner-friendly docs); a managed PaaS (Railway/Render/Fly.io) instead of a raw VPS (less ops work, but a bigger departure from the existing Docker Compose deployment model already decided in ADR-008).
- Consequences: actual account creation, payment setup, droplet provisioning, and domain purchase are owner actions — no agent can perform these (real credentials, spending money, cloud provider actions all require explicit owner action per `AGENTS.md`). Once the droplet and domain exist, deployment configuration (Compose on the droplet, Cloudflare DNS/proxy settings, secrets handling) can proceed as agent-assisted work.
- Files affected: `docs/context/PLANS.md`, `docs/context/CURRENT_STATE.md`, `docs/context/SESSION_HANDOFF.md`.
- Revisit if: cost, region/latency requirements, or a preference change makes a different provider or a managed PaaS more suitable.

## ADR-012

- ID: ADR-012
- Date: 2026-07-14
- Status: Accepted
- Context: The release process required a way to prevent an application version from starting against a database schema it doesn't understand, without breaking the existing documented deploy runbook (`scripts/optimusctl.sh update` then a separate `migrate` step), which creates a normal, expected window where new app code runs briefly against old-but-compatible schema.
- Decision: `app/migration_compat.py::check_schema_compatibility()` classifies the database's schema state relative to the app's own Alembic head into five states (`matched`, `behind`, `unmigrated`, `unsupported`, `unreachable`). Only `unsupported` and `unreachable` are treated as unsafe to serve; `behind` and `unmigrated` are tolerated. Schema incompatibility degrades `/ready` (`status: "degraded"`, kept out of load-balancer rotation) rather than crashing the process outright.
- Alternatives considered: crashing/refusing to start the process on any schema mismatch (rejected — would turn the runbook's normal deploy-order window into a routine outage, since `update` runs before `migrate`); doing no compatibility check at all (rejected — silently serving against an unrecognized/future/diverged schema is exactly the failure mode this decision exists to prevent).
- Consequences: the deploy runbook's `update`-then-`migrate` ordering remains safe by design, not by luck; a genuinely unsupported schema (future revision this app predates, or a diverged history) correctly blocks readiness instead of serving unpredictable behavior. Changing which states block readiness requires updating this ADR and `docs/context/RELEASE_CHECKLIST.md` together, since the deploy runbook depends on the current tolerance boundary.
- Files affected: `app/migration_compat.py`, `app/main.py`, `tests/test_migration_compat.py`, `tests/test_api.py`, `docs/context/RELEASE_CHECKLIST.md`.
- Revisit if: the deploy runbook's ordering changes (e.g., migrations always run before the app restarts), which would remove the need to tolerate `behind`/`unmigrated`.

## ADR-013

- ID: ADR-013
- Date: 2026-07-19
- Status: Accepted
- Context: The multi-shop pilot needs self-service recovery, session control, delegated invitations, durable account status, and a future MFA integration without storing reusable recovery or factor secrets in plaintext.
- Decision: Keep authentication lifecycle state in PostgreSQL; store password-reset and invitation tokens as hashes only; enforce account and membership status together; revoke sessions and outstanding grants on security-sensitive lifecycle changes; revalidate inviter authority at acceptance; and represent MFA factors with provider-neutral external references and lifecycle metadata rather than raw shared-secret columns.
- Alternatives considered: stateless reset/invitation tokens, application-memory lockout, trusting authority captured only when an invitation was created, or storing TOTP/shared secrets directly in the core account table.
- Consequences: lifecycle changes are auditable and transactionally enforceable across app restarts; public token responses remain generic; concurrent provisioning paths must share database row locks; an eventual MFA provider can be integrated without a schema redesign that exposes raw factor material.
- Files affected: `alembic/versions/029_account_lifecycle.py`, `app/account_security_store.py`, `app/auth.py`, `app/db_models.py`, `app/main.py`, `app/technician_store.py`, `tests/test_account_security_api.py`, `tests/e2e/test_account_lifecycle_concurrency.py`.
- Revisit if: an approved identity provider becomes the system of record for accounts/sessions or requires a different factor-secret custody model.

## ADR-014

- ID: ADR-014
- Date: 2026-07-20
- Status: Accepted
- Context: A Laravel 12 + Livewire 4 proof-of-concept was built and evaluated (per an approved investigation) to decide whether OptimusOS should migrate off FastAPI. This is a pointer entry, not the full record — see below for where the complete analysis lives, since it was large enough to warrant its own directory rather than inline text here.
- Decision: Retain and simplify the existing FastAPI/JavaScript OptimusOS. Do not migrate to Laravel, begin a phased Laravel rewrite, or run two production applications. This reaffirms ADR-001 above now that the alternative has actually been evaluated, not just deferred. The full verified comparison, weighted decision matrix, two architecture lessons the PoC surfaced (vehicle ownership modeling, environment/database validation), an 8-item ADR set (ADR-014 through ADR-021, continuing this file's numbering but held in their own files), the roadmap, and the first security-kernel phase all live in `docs/architecture/`.
- Alternatives considered: a phased Laravel migration and a full Laravel rebuild — both rejected; full reasoning in `docs/architecture/STACK-DECISION.md` §2-3.
- Consequences: Phase 1 (extracting and hardening the existing security kernel) is now the approved next implementation step, before any prompt/manual shared-execution or Sentinel work begins. The Laravel PoC repository (`/home/dejake/optimus-laravel-poc/`) is retained as research evidence, not deleted, and is not deployed.
- Files affected: `docs/architecture/README.md`, `docs/architecture/STACK-DECISION.md`, `docs/architecture/adr/ADR-014-*.md` through `ADR-021-*.md`, `docs/architecture/PHASE1-SECURITY-KERNEL-PLAN.md`.
- Revisit if: a future, separately-approved architecture review changes this decision — as a new dated ADR, never by editing `docs/architecture/STACK-DECISION.md`'s body.
- **Note for future entries in this file:** ADR-014 through ADR-021 are reserved for the detailed records in `docs/architecture/adr/`. The next available number in this file's own sequence is **ADR-022**.
