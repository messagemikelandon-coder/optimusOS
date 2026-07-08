---
name: verify-local
description: Runs the required non-billable local OptimusOS quality gates and records exact evidence. Use after a bounded implementation is complete.
disable-model-invocation: true
---
Run the repository's current documented commands. Unless the repository has intentionally changed them, use:

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/tmp/uv-cache uv run pyright
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -vv --durations=20
docker compose config -q
docker compose build backend worker
docker compose up -d
docker compose exec -T backend alembic current
```

Then run the focused non-billable runtime and Playwright checks named in the active task.

Rules:
- No live OpenAI calls.
- No real secrets.
- No production/staging writes.
- Do not hide failures or weaken checks.
- Record command, result, and relevant count in `docs/context/SESSION_HANDOFF.md` only after results exist.
