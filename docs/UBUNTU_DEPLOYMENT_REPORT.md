# Ubuntu Deployment Report

Date: 2026-06-30

## Scope

OptimusOS was made operational locally on this Ubuntu computer using the existing Optimus 7.0.1 repository as the foundation. No Railway, paid cloud resource, or production deployment was created.

## Host Inspection

- OS: Ubuntu 26.04 LTS
- Architecture: x86_64
- Kernel observed: `7.0.0-14-generic`
- RAM: 30 GiB
- Disk: `/home` had about 76 GiB free of 98 GiB
- Docker Engine: `29.1.3`
- Docker Compose: installed `2.40.3+ds1-0ubuntu1`
- Docker Buildx: installed `0.30.1-0ubuntu1`
- Node.js: installed `v22.22.1`
- npm: installed `9.2.0`
- Python host default: `3.14.4`; Docker backend uses Python 3.12

Ubuntu reported a newer kernel package is available and a reboot is recommended later. No reboot was performed during this local deployment.

## Tools Installed

Installed from Ubuntu apt repositories:

- `docker-compose-v2`
- `docker-buildx`
- `nodejs`
- `npm`

Docker Engine was already present.

## Files Changed

- `.dockerignore`
- `.env.example`
- `.gitignore`
- `Dockerfile`
- `alembic.ini`
- `alembic/env.py`
- `alembic/versions/001_optimus_os_foundation.py`
- `app/config.py`
- `app/main.py`
- `docker-compose.yml`
- `docs/CHECKPOINT.md`
- `docs/UBUNTU_DEPLOYMENT_REPORT.md`
- `ops/db/001_optimus_os_foundation.sql`
- `ops/db/002_seed_demo_data.sql`
- `ops/nginx/default.conf`
- `pyproject.toml`
- `scripts/install_systemd_service.sh`
- `scripts/optimus_worker.py`
- `scripts/optimusctl.sh`
- `start-optimus-ubuntu.sh`
- `tests/test_api.py`

No `.env` values or secrets were committed or printed into documentation.

## Commands Used

Key commands executed:

- `sudo apt-get update`
- `sudo apt-get install -y docker-compose-v2 nodejs npm`
- `sudo apt-get install -y docker-buildx`
- `git init`
- `git add .`
- `git commit -m "checkpoint: preserve existing optimus foundation"`
- `sudo docker compose -f docker-compose.yml --env-file .env up -d --build postgres redis backend worker frontend`
- `sudo docker compose -f docker-compose.yml --env-file .env run --rm backend alembic upgrade head`
- `sudo docker compose -f docker-compose.yml --env-file .env exec -T postgres psql -U optimus -d optimus_os -v ON_ERROR_STOP=1 < ops/db/002_seed_demo_data.sql`
- `curl -fsS http://127.0.0.1:8000/health`
- `curl -fsS http://127.0.0.1:8000/ready`
- `curl -fsS http://127.0.0.1:5173/ready`
- `sudo docker compose -f docker-compose.yml --env-file .env run --rm -e OPTIMUS_ACCESS_TOKEN= backend sh -c 'PYTHONUSERBASE=/tmp/pyuser PYTHONPYCACHEPREFIX=/tmp/pycache pip install --user pytest pytest-asyncio && PYTHONUSERBASE=/tmp/pyuser PYTHONPYCACHEPREFIX=/tmp/pycache PATH=/tmp/pyuser/bin:$PATH python -m pytest -q -p no:cacheprovider'`
- `node --check app/static/app.js`
- `sudo docker run --rm -v /home/dejake/optimus-server:/app:ro -w /app --entrypoint sh optimus-server-backend -c 'pip install ruff mypy && RUFF_CACHE_DIR=/tmp/ruff-cache ruff check app integration tests scripts && mypy --cache-dir /tmp/mypy-cache app integration'`
- `xdg-open http://127.0.0.1:5173`
- `sudo scripts/install_systemd_service.sh`
- `systemctl is-enabled optimusos.service`
- `systemctl status optimusos.service --no-pager`

## Runtime Services

Final Compose status showed:

- `optimus-server-postgres-1`: up, healthy, internal `5432/tcp`
- `optimus-server-redis-1`: up, healthy, internal `6379/tcp`
- `optimus-server-backend-1`: up, `127.0.0.1:8000->8000/tcp`
- `optimus-server-worker-1`: up
- `optimus-server-frontend-1`: up, `127.0.0.1:5173->80/tcp`

## Health And Readiness

Backend health:

```json
{"status":"ok","version":"7.0.1","business_name":"Landon Motor Works","business_tagline":"Mobile Mechanic Intelligence","web_search_configured":true,"owner_full_control":true,"direct_owner_chat_default":true,"agent_delegation_enabled":true,"estimator_model":"gpt-4.1 mini","estimator_fallback_model":"gpt-4.1-mini"}
```

Backend readiness:

```json
{"status":"ready","version":"7.0.1","dependencies":{"postgres":true,"redis":true}}
```

Frontend readiness proxy:

```json
{"status":"ready","version":"7.0.1","dependencies":{"postgres":true,"redis":true}}
```

## Test Results

- Pytest: 49 tests passed. Warning: `StarletteDeprecationWarning` from `fastapi.testclient` dependency path.
- Frontend syntax: `node --check app/static/app.js` exited 0.
- Ruff: `All checks passed!`
- Mypy: `Success: no issues found in 20 source files`
- Playwright: no Playwright test configuration or Playwright test files were present, so no Playwright suite was available to run.

## Browser Verification

Verified URL:

- `http://127.0.0.1:5173`

`xdg-open http://127.0.0.1:5173` exited 0. Direct HTTP verification also confirmed the frontend HTML is served and the `/ready` proxy is healthy.

Host browser note: Firefox exists as a snap, but direct `firefox --version` from this shell reported snap confinement/AppArmor was not healthy. Chrome/Chromium were not installed. The app URL was still opened through the desktop opener.

## Operations Commands

- Startup: `scripts/optimusctl.sh start`
- Shutdown: `scripts/optimusctl.sh stop`
- Restart: `scripts/optimusctl.sh restart`
- Status: `scripts/optimusctl.sh status`
- Logs: `scripts/optimusctl.sh logs`
- Backup: `scripts/optimusctl.sh backup`
- Update: `scripts/optimusctl.sh update`
- Migrations: `scripts/optimusctl.sh migrate`
- Seed synthetic demo data: `scripts/optimusctl.sh seed`
- Backend health: `scripts/optimusctl.sh health`
- Backend readiness: `scripts/optimusctl.sh ready`

Systemd:

- Enabled state: `systemctl is-enabled optimusos.service` returned `enabled`
- Status after install: `inactive (dead)`, expected because the service is a boot-time `Type=oneshot` starter and containers were already running from Compose

## Manual Actions Still Required

- Enter real secret values securely in `.env` if live OpenAI-backed features are needed.
- Reboot later to move onto the newer installed Ubuntu kernel if desired.
- Repair host Firefox snap/AppArmor if direct Firefox CLI use is needed.

## Remaining Risks

- This is a local deployment only, not a production hardening review.
- Database backup retention is manual unless a separate scheduler is added.
- The systemd unit starts/stops the Compose stack but does not perform migrations automatically on boot.
- Live AI/web research depends on valid local `.env` secrets and external network/API availability.

