# Release Checklist

Purpose: the release-candidate process for OptimusOS — versioning, what a release is built from, what must pass before one ships, and how to roll one back. This is the executable reference for "is this build safe to run," not aspirational.
Information owner: repository maintainers.
Read when: cutting a release candidate, deciding whether to deploy a build, or investigating a schema/version mismatch at runtime.
Update when: the versioning scheme, gate list, or rollback procedure changes.
Last verified date: 2026-07-14 (live-proven against a real Postgres + Redis stack on `agent/claude/shop-management-ui` — `/health` and `/ready` confirmed returning real `version`/`git_commit`/`migration_head`/`schema_compatibility` fields, `schema_compatibility: "matched"` after `alembic upgrade head`).
Relevant sources: `app/__init__.py`, `pyproject.toml`, `app/migration_compat.py`, `app/main.py` (`/health`, `/ready`), `tests/test_release.py`, `tests/test_migration_compat.py`, `tests/test_api.py`, `Dockerfile`, `docker-compose.yml`, `docs/context/DECISIONS.md` (ADR-012).

## Versioning

- Single source of truth: `__version__` in `app/__init__.py`. Every other place a version string could appear (`pyproject.toml`, the `User-Agent` header in `app/services/http.py`, `integration/optimus_adapter.py`, the marketing footer in `app/static/index.html`, test fixtures) either imports `__version__` directly or is covered by a test that fails on drift (`tests/test_release.py::test_pyproject_version_matches_app_version`). Do not hardcode a version string anywhere new — import `__version__`.
- Scheme: semantic versioning, `MAJOR.MINOR.PATCH`. Enforced by `tests/test_release.py::test_version_is_semantic_versioning_shaped`.
  - PATCH: bug fixes, no schema change, no API contract change.
  - MINOR: new functionality, additive API/schema changes, backward compatible.
  - MAJOR: breaking API contract change or a migration that isn't backward compatible with the immediately preceding app version (see Migration Compatibility below).
- Bumping the version is a manual, deliberate step as part of cutting a release candidate — not automated per-commit. Bump `app/__init__.py` and `pyproject.toml` together in the same commit.

## What a build carries

Every running instance can report exactly what it is, via `/health` and `/ready`:

- `version` — from `__version__`.
- `git_commit` — baked in at Docker build time via the `GIT_COMMIT` build arg (`docker-compose.yml` passes `${GIT_COMMIT:-unknown}`; set it explicitly with `GIT_COMMIT=$(git rev-parse HEAD) docker compose build` to get a real commit instead of `"unknown"`). Also shown in the System bay UI's "Build" tile.
- `migration_head` — the Alembic head this app version was built against (`app/migration_compat.py::get_app_migration_head()`, read from the committed migration scripts, not the database).
- `database_migration_revision` (on `/ready` only) — the revision actually applied to the connected database's `alembic_version` table.
- `schema_compatibility` (on `/ready` only) — see below.

This is the record-of-truth for "what commit and schema is actually running," independent of what any doc claims.

## Migration compatibility (see ADR-012)

`app/migration_compat.py::check_schema_compatibility()` compares the app's own migration head against the database's actual current revision and classifies the result:

| State | Meaning | Blocks readiness? |
|---|---|---|
| `matched` | Database is exactly at the app's migration head. | No |
| `behind` | Database is at a known ancestor of the app's head (normal mid-deploy window). | No |
| `unmigrated` | Database has no `alembic_version` table yet (fresh database). | No |
| `unsupported` | Database is at a revision the app's migration chain doesn't recognize at all — could be a future revision this app predates, or a diverged history. | **Yes** |
| `unreachable` | The compatibility check itself couldn't run (e.g., Postgres unreachable). | **Yes** |

**Design decision**: an unsupported or unreachable schema degrades `/ready` (`status: "degraded"`) rather than crashing the process on startup. `behind`/`unmigrated` are tolerated, not blocked. This is deliberate, not an oversight — see ADR-012 for the full rationale. In short: this repo's own documented deploy runbook (`scripts/optimusctl.sh update` then a separate `migrate` step) creates a normal, expected window where new app code runs briefly against old-but-compatible schema. Treating that window as fatal would make routine deploys always trigger a hard outage instead of the load balancer just holding traffic back until `/ready` reports true. `unsupported`/`unreachable` are different in kind — nothing about waiting fixes them — so those correctly block readiness (and therefore load-balancer traffic) rather than serving against a schema the app cannot reason about.

Do not weaken this by making `unsupported`/`unreachable` non-blocking, and do not make `behind`/`unmigrated` blocking without updating ADR-012 and the deploy runbook together — the two are load-bearing on each other.

## Release-candidate branch/tag convention (documentation only — no tag has been created)

- Release candidates are cut from `main` once every required gate below is green.
- Tag format: `vMAJOR.MINOR.PATCH` (e.g. `v7.1.0`), applied to the exact commit that was gate-verified — never a moving branch pointer.
- A release-candidate branch, if one is needed for stabilization work ahead of a tag, uses `release/vMAJOR.MINOR.x` (e.g. `release/v7.1.x`), branched from `main`.
- **No tag is created and no release is cut without explicit current-turn owner approval.** This checklist documents the convention so it exists before it's needed — it does not authorize creating one.

## Required gates before any release candidate

Run from a clean checkout of the exact commit being considered, not a long-lived working tree:

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check .
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/tmp/uv-cache uv run pyright
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
node --check app/static/app.js
docker compose config -q
docker compose build backend worker
```

Plus, against a real (throwaway) Postgres + Redis:

- Alembic upgrade from a fresh database reaches a single linear head.
- `/health` reports the expected `version`/`git_commit`/`migration_head`.
- `/ready` reports `status: "ready"` and `schema_compatibility: "matched"` once migrations are applied.
- `scripts/scan_logs_for_secrets.py` against the stack's logs finds nothing.

All of the above are already enforced in CI (`.github/workflows/ci.yml`) except the live `/health`/`/ready` schema-compatibility proof, which is currently a manual step (see Follow-up below).

## Rollback criteria

Roll back a deployed release if, after deploy:

- `/health` or `/ready` fails to return `200` within the deploy runbook's expected window.
- `/ready` reports `schema_compatibility: "unsupported"` or `"unreachable"` and does not self-resolve within the expected `migrate` step window.
- The post-deploy authenticated smoke test (Part C's E2E suite, or a manual equivalent) fails on a path that passed against the previous release.
- Error-rate or log secret-scan alerting fires (once monitoring/alerting from Phase 6 Part H/I exists — not yet wired for staging as of this checklist).

## Rollback procedure

Use `scripts/optimusctl.sh rollback` (retags the previous image back to `:latest` and restarts) — already built and rehearsed once in Phase 5 (see `docs/context/PLANS.md`). If the rollback also requires a schema downgrade (a MAJOR-version release with a non-backward-compatible migration), use `scripts/optimusctl.sh migrate-down <revision>` **before** rolling the image back, so the older app version never runs against a newer schema it doesn't understand — the same `unsupported` classification above is what would catch this if the order were reversed, but the intent is not to depend on that safety net for an ordinary rollback.

## Follow-up not yet done

- Wire the live `/health`/`/ready` schema-compatibility proof above into a CI job (currently a manual step performed against a throwaway Docker Postgres/Redis pair).
- Automate release-notes generation from merged PRs (see `docs/RELEASE_NOTES.md` for the current manual version).
- Branch protection on `main` is still not enabled (tracked in `docs/context/PLANS.md` Phase 6 Part A) — a release-candidate tag currently has no CI-enforced guarantee that the tagged commit passed required checks beyond having been merged through the existing PR-gate discipline.
