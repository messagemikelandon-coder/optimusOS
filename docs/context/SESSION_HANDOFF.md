# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex session.
Information owner: the active Codex session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-02.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/DECISIONS.md`, `docs/context/KNOWN_ISSUES.md`, `git status`.

## Current objective

The Customer and Vehicle slices are complete and verified. The next substantial task can begin `Estimate -> Approval -> Work Order` without reworking auth, session, context, database, customer, or vehicle foundations.

## Completed

- Confirmed the repository root is `/home/dejake/optimus-server`.
- Confirmed the active branch is `feat/vehicle-management`.
- Confirmed `060ab6869a9c129136ea406d53ac2c72b96e9cdc` is already an ancestor of `HEAD`.
- Preserved and completed the existing context-manager WIP in `alembic/versions/003_context_entries.py`, `app/context_store.py`, `app/db_models.py`, `app/models.py`, `app/config.py`, and `app/main.py`.
- Added database-level scope consistency checks for `context_entries`.
- Implemented authenticated context CRUD with project/session scoping and session-over-project fallback on session reads.
- Added sanitized `503` handling for context storage failures and auth storage failures.
- Added focused backend coverage in `tests/test_context_api.py` for auth rejection, CRUD, conflict handling, scope fallback, session/project isolation, cross-user isolation, limits, secret rejection, and storage-failure sanitization.
- Verified root `ruff`, `pyright`, and `pytest` all pass.
- Verified `docker compose config -q`, `docker compose build backend worker`, `docker compose up -d`, `docker compose ps`, and `docker compose exec -T backend alembic current`.
- Applied and verified Alembic migration `003_context_entries` in the live backend container.
- Verified live `GET /health`, `GET /ready`, `GET /openapi.json`, and browser login/session-restore/logout/location flows against `127.0.0.1`.
- Verified live authenticated context write/read, session fallback behavior, second-session isolation, unrelated-project isolation, backend restart persistence, full Compose restart persistence, and controlled Redis/PostgreSQL dependency-failure behavior.
- Added owner-scoped `Customer` persistence in `app/db_models.py` plus Alembic migration `004_customers`.
- Added customer validation, normalization, and owner-scoped data access in `app/customer_store.py`.
- Added authenticated customer endpoints in `app/main.py` for create, list, get, update, and archive.
- Extended the static frontend in `app/static/index.html`, `app/static/app.js`, and `app/static/styles.css` with a Customers page, list/search/filter UI, detail panel, create/edit form, and archive flow.
- Added backend customer coverage in `tests/test_customers_api.py` and expanded UI coverage in `tests/test_official_ui.py`.
- Verified live customer CRUD/search/archive/isolation against the running backend and verified customer persistence across backend/worker restart.
- Verified an authenticated Playwright Customers UI smoke for login, create, search, update, archive, and archived filtering.
- Confirmed the existing vehicle backend slice already reused the customer ownership helper path instead of creating parallel authorization logic.
- Extended the static frontend in `app/static/index.html`, `app/static/app.js`, and `app/static/styles.css` with vehicle management inside Customer detail plus a standalone Vehicles page.
- Added selected-vehicle session-context writes and best-effort restore logic that re-fetches the authoritative database record before trusting a stored reference.
- Extended `scripts/ui_connection_audit_playwright.js` to cover the non-billable live vehicle workflow, including customer creation, vehicle create/search/update/archive, and lightweight selected-vehicle context storage.
- Verified live vehicle CRUD/search/archive/isolation against the running backend and verified vehicle persistence across a Compose service restart.

## Verified

- The authenticated baseline is already integrated and was not re-merged or duplicated.
- No separate React or repo-local frontend package/toolchain exists.
- The canonical FastAPI app now exposes `/api/context/{project_key}` and `/api/context/{project_key}/{context_key}` backed by PostgreSQL persistence.
- The canonical FastAPI app now also exposes `/api/customers` and `/api/customers/{customer_id}` backed by PostgreSQL `customers` records.
- The canonical FastAPI app now also exposes `/api/customers/{customer_id}/vehicles`, `/api/vehicles`, and `/api/vehicles/{vehicle_id}` backed by PostgreSQL `vehicles` records.
- Redis-down context requests return a structured `503` dependency error.
- PostgreSQL-down protected context requests return a sanitized `503` auth storage error without leaking raw DB details.
- Customer storage remains authoritative in PostgreSQL; the context manager stores at most a lightweight selected-customer reference.
- Vehicle storage remains authoritative in PostgreSQL; the context manager stores at most a lightweight selected-vehicle reference.

## Files changed

- `.gitignore`
- `alembic/versions/003_context_entries.py`
- `app/auth.py`
- `app/config.py`
- `app/context_store.py`
- `app/customer_store.py`
- `app/db_models.py`
- `app/main.py`
- `app/models.py`
- `app/static/index.html`
- `app/static/app.js`
- `app/static/styles.css`
- `alembic/versions/004_customers.py`
- `alembic/versions/005_vehicles.py`
- `pyproject.toml`
- `pyrightconfig.json`
- `tests/conftest.py`
- `tests/test_context_api.py`
- `tests/test_customers_api.py`
- `tests/test_official_ui.py`
- `scripts/ui_connection_audit_playwright.js`
- `docs/context/ARCHITECTURE.md`
- `docs/context/CURRENT_STATE.md`
- `docs/context/KNOWN_ISSUES.md`
- `docs/context/PRODUCT.md`
- `docs/context/SESSION_HANDOFF.md`
- `PLANS.md`

## Tests and results

- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .` passed.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` passed.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright` passed with `0 errors, 0 warnings, 0 informations`.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` passed with `96` tests.
- `docker compose up -d --build backend worker frontend` passed.
- `docker compose exec -T backend alembic upgrade head` applied `005_vehicles`.
- `docker compose exec -T backend alembic current` reported `005_vehicles (head)`.
- `node --check app/static/app.js` passed.
- `docker compose restart backend worker frontend` passed.
- Live runtime verification passed for customer and vehicle CRUD, VIN and plate search, mileage update, archive, cross-user isolation, lightweight context isolation, and restart persistence.
- `env OPTIMUS_AUDIT_SKIP_BILLABLE=1 node scripts/ui_connection_audit_playwright.js` passed for login, customer create, vehicle create/search/update/archive, selected-vehicle context storage, logout, and expired-session handling.

## Uncommitted changes

- The vehicle frontend, live vehicle audit script, and updated context docs are currently in the working tree and are not yet committed.
- Review regenerated screenshots under `docs/screenshots/auth-integration/` before staging them.

## Current blockers

- No confirmed blocker remains for the authenticated/context/customer baseline itself.
- Billable live chat and estimate flows remain intentionally unverified in this session.

## Exact next action

Start the `Estimate -> Approval -> Work Order` slice on top of the verified authenticated/context/customer/vehicle baseline. Reuse the existing auth/session stack, PostgreSQL ownership model, and lightweight context reference pattern rather than creating parallel systems.

## Commands to resume

```bash
git status --short --branch
git diff --stat
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/tmp/uv-cache uv run pyright
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -vv --durations=20
docker compose ps
docker compose exec -T backend alembic current
node --check app/static/app.js
```

## Decisions made

- Keep one canonical auth/session system and route all context persistence through it.
- Treat session scope as an override layer that falls back to project scope for reads.
- Sanitize DB/storage failures in auth and context paths instead of logging or returning raw exception text.
- Keep customer records in PostgreSQL as the source of truth and limit context storage to lightweight customer references only.
- Return `404` for out-of-scope customer lookups instead of revealing cross-user existence.

## Context documents requiring updates

- Update `CURRENT_STATE.md`, `KNOWN_ISSUES.md`, and `SESSION_HANDOFF.md` again only after the next substantial verified product slice changes reality.
