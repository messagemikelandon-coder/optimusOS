# Decisions

Purpose: lightweight architecture decision record for verified repository choices.
Information owner: repository maintainers and owners approving architectural direction.
Read when: changing architecture, auth, deployment, or data flow.
Update when: a decision is made, superseded, or explicitly revisited.
Last verified date: 2026-07-01.
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
