# Current State

Purpose: concise operational snapshot of the verified current repository state.
Information owner: repository maintainers and the current Codex session author.
Read when: before every task, together with `SESSION_HANDOFF.md`.
Update when: the branch, working status, live stack status, migrations, or quality-gate results change.
Last verified date: 2026-07-04.
Relevant sources: `git status --short --branch`, `git branch --show-current`, `git log -1 --oneline --decorate`, `docker compose build backend worker`, `docker compose up -d backend worker frontend`, `docker compose ps`, `docker compose exec -T backend alembic upgrade head`, `docker compose exec -T backend alembic current`, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`, `node --check app/static/app.js`, `node --check scripts/ui_connection_audit_playwright.js`, `env OPTIMUS_AUDIT_SKIP_BILLABLE=1 node scripts/ui_connection_audit_playwright.js`, live authenticated API proof for `/api/customers`, `/api/vehicles`, and `/api/context/*` against `http://127.0.0.1:5173`.

## Operational Snapshot

- Active development phase: the authenticated/context baseline remains green, the Customer plus Vehicle slices are implemented and verified, and the Estimate Approval slice is implemented in source with local quality gates plus non-billable live-stack verification complete.
- Current branch: `feat/vehicle-management`.
- Current HEAD: `b167c2fb52f6e99b067eeccaeadf02634a5c5dac`.
- Auth baseline status: commit `060ab6869a9c129136ea406d53ac2c72b96e9cdc` is an ancestor of `HEAD`.
- Current verified functionality: owner login/logout/me, server-side sessions, protected location resolution, owner-scoped context CRUD, project/session scope separation, session-over-project fallback for session reads, owner-scoped customer CRUD/list/search/archive, owner-scoped vehicle CRUD/list/search/archive, lightweight session-scoped customer, vehicle, and estimate references, saved estimate CRUD plus revisioning, estimate approval-link generation and approval audit persistence, controlled dependency failures, health, readiness, OpenAPI delivery, and static frontend delivery.
- Customer slice status: implemented with canonical PostgreSQL persistence in `customers`, authenticated endpoints in `app/main.py`, static frontend workflow in `app/static/`, and lightweight session-scoped customer context references only.
- Vehicle slice status: implemented with canonical PostgreSQL persistence in `vehicles`, authenticated endpoints in `app/main.py`, a shared ownership model that reuses the customer helper path, static frontend workflows in `app/static/`, and lightweight session-scoped selected-vehicle references only.
- Estimate Approval slice status: implemented in source with canonical PostgreSQL persistence in `estimates`, `estimate_revisions`, `estimate_approval_requests`, and `estimate_approval_events`, authenticated owner endpoints in `app/main.py`, customer-facing approval routes served from the same static frontend, and lightweight session-scoped selected-estimate references only.
- Customer endpoints: `POST /api/customers`, `GET /api/customers`, `GET /api/customers/{customer_id}`, `PATCH /api/customers/{customer_id}`, and `DELETE /api/customers/{customer_id}` for archive.
- Vehicle endpoints: `POST /api/customers/{customer_id}/vehicles`, `GET /api/customers/{customer_id}/vehicles`, `GET /api/vehicles`, `GET /api/vehicles/{vehicle_id}`, `PATCH /api/vehicles/{vehicle_id}`, and `DELETE /api/vehicles/{vehicle_id}` for archive.
- Estimate endpoints: `POST /api/estimates`, `GET /api/estimates`, `GET /api/estimates/{estimate_id}`, `PATCH /api/estimates/{estimate_id}`, `POST /api/estimates/{estimate_id}/create-revision`, `POST /api/estimates/{estimate_id}/send-for-approval`, `GET /approval`, `POST /api/estimate-approval/view`, `POST /api/estimate-approval/approve`, `POST /api/estimate-approval/decline`, and `GET /api/estimates/{estimate_id}/approval-history`.
- Latest quality-gate results: on 2026-07-04, `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`, `node --check app/static/app.js`, and `node --check scripts/ui_connection_audit_playwright.js` all passed from the repository root.
- Live stack status: on 2026-07-04, `docker compose build backend worker`, `docker compose up -d backend worker frontend`, `docker compose exec -T backend alembic upgrade head`, `docker compose exec -T backend alembic current`, and `docker compose ps` all succeeded. `docker compose ps` showed healthy PostgreSQL and Redis plus running backend, worker, and frontend containers. The authenticated non-billable Playwright smoke passed again after the rebuild against `http://127.0.0.1:5173`.
- Migration status: `006_estimate_approvals` is the current live Alembic head inside the backend container.
- Runtime context proof: authenticated project-scope and session-scope writes succeeded; session scope returned the session override while a second owner session saw only project fallback; an unrelated project returned zero entries; project-scope data persisted across backend/worker restart and full Compose restart.
- Runtime customer proof: an authenticated owner created a customer, retrieved it, updated it, confirmed company/email search hit, archived it, confirmed default active listing excluded it, confirmed archived listing returned it, confirmed a second owner received `404`, restarted backend and worker, and confirmed the archived customer still persisted after restart.
- Runtime vehicle proof: an authenticated owner created a customer, added two vehicles, confirmed VIN and plate search hits, updated mileage to `126500`, confirmed a second owner received `404` for both vehicle lookups before and after restart, archived one vehicle, confirmed active and archived listings split correctly, restarted Compose services, and confirmed both active and archived vehicle records still persisted after restart.
- Runtime estimate-approval proof: source-backed tests cover create, approve, decline, revision lock, token expiry, token reuse, cross-user isolation, payment-plan acknowledgement, audit immutability, sanitized storage failure handling, and SQLite restart persistence. Live non-billable browser proof verified the rebuilt stack still preserves auth, customer, vehicle, and lightweight selected-estimate context paths without exposing tokens. Billable live estimate-generation and approval-link flows remain intentionally unrun pending owner approval because they may spend money through OpenAI-backed requests.
- Runtime context proof for vehicle references: the browser audit stored only lightweight session-scoped selected customer and selected vehicle references; the direct API proof confirmed a second owner session saw no customer or vehicle context entries from the owner session.
- Dependency-failure proof: with Redis stopped, the context API returned `503` with `context_dependencies_unavailable` and `unavailable_dependencies=["redis"]`; with PostgreSQL stopped and settled, the protected context route returned `503` with `Authentication storage is unavailable.`; both dependencies recovered cleanly and `/ready` returned to `ready`.
- Frontend toolchain status: no repo-local `package.json` or separate frontend source tree exists, so no additional frontend lint/typecheck/build command applies beyond static asset verification, `node --check app/static/app.js`, `node --check scripts/ui_connection_audit_playwright.js`, and the authenticated Playwright smoke.
- Owner-bootstrap status without credentials: the first owner account is created only when `OPTIMUS_OWNER_USERNAME` and `OPTIMUS_OWNER_PASSWORD` are present; no credential values are stored here.
- Frontend URL: `http://127.0.0.1:5173`.
- Backend URL: `http://127.0.0.1:8000`.
- OpenAPI URL: `http://127.0.0.1:8000/openapi.json`.
- Next approved implementation phase: finish live billable Estimate Approval runtime proof, update approval documentation from that proof, and only then begin the Work Order slice.
- Current blockers: live billable estimate-generation and customer approval proof remain intentionally blocked pending explicit owner approval because they may spend money through OpenAI-backed requests.

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
- Vehicle UI selection may write a lightweight `{id, customer_id, display_name}` session-scoped context reference for assistive memory, but full vehicle records are not stored in context.
- Estimate UI selection may write a lightweight `{id, estimate_number, revision_number}` session-scoped context reference for assistive memory, but approval tokens, signatures, and payment authorization details are not stored in context.
- OpenAI usage stays server-side in `app/services/openai_web.py` and `app/services/optimus_chat.py`.
- The canonical backend, frontend, migration, context, and Compose paths are `app/`, `app/static/`, `alembic/`, `docs/context/`, and `docker-compose.yml` plus `ops/nginx/default.conf`.
