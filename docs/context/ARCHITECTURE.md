# Architecture

Purpose: verified current-system architecture and the boundary between current and target designs.
Information owner: repository maintainers.
Read when: working on backend, frontend, deployment, or integration tasks.
Update when: the serving stack, data flow, auth model, or deployment topology changes.
Last verified date: 2026-07-04.
Relevant sources: `docker-compose.yml`, `ops/nginx/default.conf`, `app/main.py`, `app/auth.py`, `app/orchestrator.py`, `app/services/openai_web.py`, `app/services/optimus_chat.py`, `app/db.py`, `app/db_models.py`, `alembic/versions/002_authentication_tables.py`.

## Current Architecture

- Browser loads the static frontend from Nginx at `http://127.0.0.1:5173`.
- The frontend calls relative `/api/...` paths, so browser requests stay same-origin through the Nginx proxy.
- Nginx serves `app/static/` and proxies `/api/`, `/health`, and `/ready` to FastAPI.
- FastAPI provides auth, health, readiness, context, customer, vehicle, estimate, estimate-approval, chat, and location endpoints.
- PostgreSQL stores users and sessions.
- Redis backs the application worker path in `docker-compose.yml`.
- The background worker runs as `python -m scripts.optimus_worker`.
- OpenAI requests remain server-side in the chat and research services.
- Alembic manages schema evolution for the PostgreSQL database.

## Mermaid Diagram

```mermaid
flowchart LR
  Browser[Browser]
  Nginx[Nginx frontend service\n127.0.0.1:5173]
  FastAPI[FastAPI app\napp.main:app\n127.0.0.1:8000]
  Postgres[(PostgreSQL)]
  Redis[(Redis)]
  Worker[Background worker]
  OpenAI[OpenAI Responses / web research]

  Browser -->|GET /, /static/*, /api/*| Nginx
  Nginx -->|proxy /api/*, /health, /ready| FastAPI
  FastAPI --> Postgres
  FastAPI --> Redis
  FastAPI --> OpenAI
  Worker --> Postgres
  Worker --> Redis
```

## Current Boundaries

- Auth is cookie-backed and server-side.
- Browser code never receives server API keys.
- Same-origin `/api/` routing is the expected local-development path.
- The repository does not contain a separate React or Vite source tree.
- Customer, vehicle, estimate, estimate revision, and estimate approval records are stored in PostgreSQL and exposed through owner-scoped FastAPI routes plus a customer-facing approval route that relies on hashed approval tokens.

## Target Architecture

- No approved architectural replacement exists at present.
- Customer and vehicle modules are now implemented on the current FastAPI plus PostgreSQL stack.
- Work orders and invoices are not yet implemented in the source tree.
- Estimate approval persistence and API routes are implemented in the current FastAPI plus PostgreSQL stack, but the billable live browser proof remains intentionally deferred pending owner approval.
- Future changes must be recorded in `DECISIONS.md` before this file is rewritten to describe them as current.
