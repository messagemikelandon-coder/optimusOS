# Current State

Purpose: concise operational snapshot of the verified current repository state.
Information owner: repository maintainers and the current Codex session author.
Read when: before every task, together with `SESSION_HANDOFF.md`.
Update when: the branch, working status, live stack status, migrations, or quality-gate results change.
Last verified date: 2026-07-01.
Relevant sources: `git status`, `git branch --show-current`, `git log -5 --oneline`, `scripts/optimusctl.sh`, `docs/frontend-audit.md`, `docs/UBUNTU_DEPLOYMENT_REPORT.md`, `app/main.py`, `app/auth.py`, `alembic/versions/002_authentication_tables.py`.

## Operational Snapshot

- Active development phase: context-management and documentation routing.
- Current branch: `chore/context-management`.
- Current HEAD: `14e3ea57e23dd5fc7a6d3616169a8ba4e4565791`.
- Latest verified passing commit: `e6a2002` (`chore: preserve passing local server baseline`).
- Current verified functionality: owner login/logout/me, server-side sessions, protected chat, protected estimate, protected location resolution, health, readiness, and static frontend delivery.
- Currently broken functionality: no confirmed application defect from the source audit; the live-stack refresh could not be rerun in this sandbox because socket access is blocked.
- Latest quality-gate results: `docs/UBUNTU_DEPLOYMENT_REPORT.md` recorded passing `pytest`, `ruff`, `mypy`, and frontend syntax checks on 2026-06-30.
- Live stack status: last verified on 2026-06-30 in `docs/frontend-audit.md` and `docs/UBUNTU_DEPLOYMENT_REPORT.md`; current sandbox prevented a fresh socket check.
- Migration status: `002_authentication_tables` is the current auth migration and was reported as `head` in `docs/frontend-audit.md`.
- Owner-bootstrap status without credentials: the first owner account is created only when `OPTIMUS_OWNER_USERNAME` and `OPTIMUS_OWNER_PASSWORD` are present; no credentials are stored here.
- Frontend URL: `http://127.0.0.1:5173`.
- Backend URL: `http://127.0.0.1:8000`.
- OpenAPI URL: `http://127.0.0.1:8000/openapi.json`.
- Next approved implementation phase: protected-flow verification and stabilization work, not the futuristic frontend redesign.
- Current blockers: no live socket access in the Codex sandbox for a fresh stack check.

## Exact Startup Commands

```bash
scripts/optimusctl.sh start
scripts/optimusctl.sh migrate
scripts/optimusctl.sh bootstrap-owner
scripts/optimusctl.sh status
```

## Exact Verification Commands

```bash
git diff --check
git status
git diff --stat
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/tmp/uv-cache uv run pyright
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -vv --durations=20
scripts/optimusctl.sh health
scripts/optimusctl.sh ready
```

## Working Notes

- The backend is FastAPI in `app.main:app`.
- The browser-facing frontend is the static Nginx-served interface in `app/static/`.
- Protected flows use the HttpOnly session cookie defined in `app/auth.py`.
- OpenAI usage stays server-side in `app/services/openai_web.py` and `app/services/optimus_chat.py`.
