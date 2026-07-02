# Current State

Purpose: concise operational snapshot of the verified current repository state.
Information owner: repository maintainers and the current Codex session author.
Read when: before every task, together with `SESSION_HANDOFF.md`.
Update when: the branch, working status, live stack status, migrations, or quality-gate results change.
Last verified date: 2026-07-02.
Relevant sources: `git status --short --branch`, `git branch --show-current`, `git merge-base --is-ancestor 060ab6869a9c129136ea406d53ac2c72b96e9cdc HEAD`, `git diff --stat`, `docker compose config -q`, `docker compose build backend worker`, `docker compose up -d`, `docker compose ps`, `docker compose exec -T backend alembic current`, `docker compose logs --tail=200 backend worker frontend`, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -vv --durations=20`, `node --check app/static/app.js`, authenticated backend container runtime proof for `/api/customers`, authenticated Playwright customer UI smoke against `http://127.0.0.1:5173`.

## Operational Snapshot

- Active development phase: the authenticated/context baseline remains green and the Customer business slice is now implemented and verified on top of it.
- Current branch: `chore/context-management`.
- Current HEAD: `1af4a0da6b25af0c9f77c7f99d60c8e1c8bb4284`.
- Auth baseline status: commit `060ab6869a9c129136ea406d53ac2c72b96e9cdc` is an ancestor of `HEAD`.
- Current verified functionality: owner login/logout/me, server-side sessions, protected location resolution, owner-scoped context CRUD, project/session scope separation, session-over-project fallback for session reads, owner-scoped customer CRUD/list/search/archive, controlled dependency failures, health, readiness, OpenAPI delivery, and static frontend delivery.
- Customer slice status: implemented with canonical PostgreSQL persistence in `customers`, authenticated endpoints in `app/main.py`, static frontend workflow in `app/static/`, and lightweight session-scoped customer context references only.
- Customer endpoints: `POST /api/customers`, `GET /api/customers`, `GET /api/customers/{customer_id}`, `PATCH /api/customers/{customer_id}`, and `DELETE /api/customers/{customer_id}` for archive.
- Latest quality-gate results: on 2026-07-02, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright`, and `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -vv --durations=20` all passed from the repository root. `pytest` passed with `88` tests.
- Live stack status: on 2026-07-02, `docker compose config -q`, `docker compose build backend worker`, and `docker compose up -d` all succeeded. `docker compose ps` showed healthy PostgreSQL and Redis plus running backend, worker, and frontend containers. Authenticated live runtime proof succeeded for `/api/customers`, and an authenticated Playwright Customers UI smoke succeeded against `http://127.0.0.1:5173`.
- Migration status: `004_customers` is the current live Alembic head inside the backend container.
- Runtime context proof: authenticated project-scope and session-scope writes succeeded; session scope returned the session override while a second owner session saw only project fallback; an unrelated project returned zero entries; project-scope data persisted across backend/worker restart and full Compose restart.
- Runtime customer proof: an authenticated owner created a customer, retrieved it, updated it, confirmed company/email search hit, archived it, confirmed default active listing excluded it, confirmed archived listing returned it, confirmed a second owner received `404`, restarted backend and worker, and confirmed the archived customer still persisted after restart.
- Dependency-failure proof: with Redis stopped, the context API returned `503` with `context_dependencies_unavailable` and `unavailable_dependencies=["redis"]`; with PostgreSQL stopped and settled, the protected context route returned `503` with `Authentication storage is unavailable.`; both dependencies recovered cleanly and `/ready` returned to `ready`.
- Frontend toolchain status: no repo-local `package.json` or separate frontend source tree exists, so no additional frontend lint/typecheck/build command applies beyond static asset verification, `node --check app/static/app.js`, and the authenticated Playwright smoke.
- Owner-bootstrap status without credentials: the first owner account is created only when `OPTIMUS_OWNER_USERNAME` and `OPTIMUS_OWNER_PASSWORD` are present; no credential values are stored here.
- Frontend URL: `http://127.0.0.1:5173`.
- Backend URL: `http://127.0.0.1:8000`.
- OpenAPI URL: `http://127.0.0.1:8000/openapi.json`.
- Next approved implementation phase: `Vehicle -> Estimate -> Approval -> Work Order` on top of the verified auth/context/customer foundation.
- Current blockers: billable live chat and estimate flows were intentionally not rerun in this session because they may spend money through OpenAI-backed calls.

## Exact Startup Commands

```bash
scripts/optimusctl.sh start
scripts/optimusctl.sh migrate
scripts/optimusctl.sh bootstrap-owner
scripts/optimusctl.sh status
docker compose config -q
docker compose build backend worker
docker compose up -d
```

## Exact Verification Commands

```bash
git diff --check
git status --short --branch
git diff --stat
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/tmp/uv-cache uv run pyright
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -vv --durations=20
docker compose ps
docker compose exec -T backend alembic current
docker compose logs --tail=200 backend worker
node --check app/static/app.js
```

## Working Notes

- The backend is FastAPI in `app.main:app`.
- The browser-facing frontend is the static Nginx-served interface in `app/static/`.
- Protected flows use the HttpOnly session cookie defined in `app/auth.py`.
- Context persistence is stored in `context_entries` and reuses the existing `user_accounts` plus `auth_sessions` identity/session model.
- Business customer persistence is stored in `customers` and remains the authoritative source of customer data.
- Project-scope context persists across session changes; session-scope context is isolated to the originating auth session and falls back to project scope during session reads.
- Customer UI selection may write a lightweight `{id, display_name}` session-scoped context reference for assistive memory, but full customer records are not stored in context.
- OpenAI usage stays server-side in `app/services/openai_web.py` and `app/services/optimus_chat.py`.
- The canonical backend, frontend, migration, context, and Compose paths are `app/`, `app/static/`, `alembic/`, `docs/context/`, and `docker-compose.yml` plus `ops/nginx/default.conf`.
