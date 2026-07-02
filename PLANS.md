# Plans

Purpose: active repository plan for convergence and the next implementation slice.
Information owner: repository maintainers and the active Codex session author.
Read when: choosing the next repository task or checking whether prerequisite baseline work is actually finished.
Update when: the active implementation plan, blockers, or readiness assessment changes.
Last verified date: 2026-07-02.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/KNOWN_ISSUES.md`, `docs/context/SESSION_HANDOFF.md`, `app/main.py`, `app/context_store.py`, `docker-compose.yml`, `pyproject.toml`.

## Active plan

1. Authenticated/context baseline
   Status: Complete.
   Evidence: the authenticated baseline commit `060ab6869a9c129136ea406d53ac2c72b96e9cdc` is already merged into `chore/context-management`; root `ruff`, `pyright`, and `pytest` pass; Docker Compose build/up passed; migration `003_context_entries` is live; browser auth smoke passed; context CRUD, scope isolation, restart persistence, and controlled dependency failures are verified.

2. Customer vertical slice
   Status: Complete.
   Scope: authenticated owner-scoped customer CRUD, list, search, pagination, archive, and static frontend workflow only.
   Evidence:
   - Alembic migration `004_customers` is live.
   - `/api/customers` create/list/get/update/archive routes are implemented and verified.
   - Root `ruff`, `pyright`, and `pytest` pass with `88` tests.
   - Live backend runtime proof passed for create, retrieve, update, search, archive, cross-user `404`, and restart persistence.
   - Authenticated Playwright Customers UI smoke passed for login, create, search, update, archive, and archived filtering.

3. Vehicle and downstream business slice
   Status: Not started.
   Scope: `Vehicle -> Estimate -> Approval -> Work Order`.
   Constraint: reuse the existing auth/session/customer/context foundation instead of adding parallel models, route families, or client state systems.
   Planned sequence:
   - Add canonical PostgreSQL tables and Alembic migrations for vehicles and later downstream business records.
   - Extend `app/db_models.py` with owner-scoped relationships from customers to vehicles and later workflow records.
   - Extend `app/models.py` with safe request and response contracts that hide internal IDs, supplier cost, markup, and raw backend errors.
   - Add authenticated CRUD and workflow endpoints in `app/main.py`, reusing `get_db_session`, `get_current_auth_context`, and existing error-handling patterns.
   - Extend `app/static/index.html`, `app/static/app.js`, and `app/static/styles.css` for the next business views and API calls instead of introducing a separate frontend stack.
   - Add focused pytest coverage for authorization, isolation, persistence, and workflow transitions, plus targeted UI/runtime checks for each slice.

4. Deferred runtime verification
   Status: Intentionally deferred.
   Scope: billable live chat and estimate flows.
   Reason: these paths may spend money through OpenAI-backed requests and were not rerun in this customer task.
