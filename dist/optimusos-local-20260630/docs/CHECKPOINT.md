# OptimusOS Checkpoint

Date: 2026-06-30

## Repository State

- Initial project foundation preserved in Git commit `fc9ba0a` (`checkpoint: preserve existing optimus foundation`).
- `.env`, virtual environments, backups, logs, and generated caches are excluded from Git.
- No `AGENTS.md` file existed in the repository before changes.
- No `docs/` directory existed before this deployment checkpoint.

## Local Deployment State

- Local Docker Compose stack is operational on Ubuntu.
- Published ports are loopback-only:
  - Backend: `127.0.0.1:8000`
  - Frontend: `127.0.0.1:5173`
- PostgreSQL and Redis are internal Docker services only and are not publicly published.
- Alembic revision `001_optimus_os_foundation` was applied successfully.
- Synthetic demonstration data was seeded into `demo_service_requests`.
- Restart-after-reboot is configured through enabled systemd unit `optimusos.service`.

## Verification Snapshot

- Backend health: `http://127.0.0.1:8000/health` returned `status=ok`, version `7.0.1`.
- Backend readiness: `http://127.0.0.1:8000/ready` returned `status=ready`, PostgreSQL `true`, Redis `true`.
- Frontend readiness proxy: `http://127.0.0.1:5173/ready` returned `status=ready`, PostgreSQL `true`, Redis `true`.
- Frontend URL opened through `xdg-open http://127.0.0.1:5173`.
- Pytest: 49 tests passed with one dependency deprecation warning.
- Frontend JavaScript syntax: `node --check app/static/app.js` passed.
- Ruff: all checks passed.
- Mypy: success, no issues in 20 source files.

## Operator Commands

- Start: `scripts/optimusctl.sh start`
- Stop: `scripts/optimusctl.sh stop`
- Restart: `scripts/optimusctl.sh restart`
- Status: `scripts/optimusctl.sh status`
- Logs: `scripts/optimusctl.sh logs`
- Migrate: `scripts/optimusctl.sh migrate`
- Seed demo data: `scripts/optimusctl.sh seed`
- Backup PostgreSQL: `scripts/optimusctl.sh backup`
- Update local stack: `scripts/optimusctl.sh update`
- Health: `scripts/optimusctl.sh health`
- Readiness: `scripts/optimusctl.sh ready`

