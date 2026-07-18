# Release Checklist

Purpose: the release-candidate process for OptimusOS — versioning, what a release is built from, what must pass before one ships, the exact ordered deployment steps, and how to roll one back. This is the executable reference for "is this build safe to run" and "how do I actually run it," not aspirational.
Information owner: repository maintainers.
Read when: cutting a release candidate, deciding whether to deploy a build, actually executing a deploy, or investigating a schema/version mismatch at runtime.
Update when: the versioning scheme, gate list, deployment steps, or rollback procedure changes.
Last verified date: 2026-07-17 (Phase 6 Part I staging-verification pass, live-proven against a real docker-compose-managed Postgres + Redis stack, not a throwaway single container: fresh-database migration reached a single linear head; `/health`/`/ready` confirmed the exact built commit and `schema_compatibility: "matched"`; a real `scripts/scan_logs_for_secrets.py` scan of the real container logs found nothing; the Part C authenticated Playwright suite passed against a separate real browser/Postgres/session stack; confirmed zero Scheduling-code changes across this session's full diff range).
Relevant sources: `app/__init__.py`, `pyproject.toml`, `app/migration_compat.py`, `app/main.py` (`/health`, `/ready`), `tests/test_release.py`, `tests/test_migration_compat.py`, `tests/test_api.py`, `tests/e2e/`, `scripts/scan_logs_for_secrets.py`, `scripts/optimusctl.sh`, `Dockerfile`, `docker-compose.yml`, `docs/context/DECISIONS.md` (ADR-012), `docs/context/MONITORING.md`.

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
- `scripts/check_shop_id_orphans.py` reports zero orphan `shop_id` rows before running migration `025_shop_id_not_null` against any database with pre-existing data (`/goal` Phase 3 slice 6) — the migration itself also refuses to proceed if any are found, but running the script first gives an actionable report ahead of a deploy rather than discovering it mid-migration.
- `/health` reports the expected `version`/`git_commit`/`migration_head`.
- `/ready` reports `status: "ready"` and `schema_compatibility: "matched"` once migrations are applied.
- `scripts/scan_logs_for_secrets.py` against the stack's logs finds nothing (`python -m scripts.scan_logs_for_secrets --project <compose-project-name> --services backend worker`).
- The Part C authenticated Playwright suite passes: `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/e2e -v` (real browser, real Postgres, real login — exercises the full customer → vehicle → estimate → approval → work order → invoice → payment chain end to end).
- Customer-facing HTML/PDF field exclusion: `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_invoices_api.py -k "html or pdf or exclud"` passes (asserts no supplier cost/markup/internal research ever appears in a customer-facing invoice document).
- **Confirm no Scheduling code was touched** if this release wasn't meant to include Scheduling changes: `git diff --name-only <previous-release-commit> <candidate-commit> | grep -i schedul` should be empty, and `git diff <previous-release-commit> <candidate-commit> -- app/static/app.js app/static/index.html | grep -i scheduling` should be empty too (Scheduling-adjacent frontend changes can hide in otherwise-unrelated diff hunks to shared files) — this check exists because Scheduling was mid-development in an earlier phase and needed to stay out of releases until explicitly ready; keep running it until this note is removed.
- **Backup, restore, and rollback rehearsal** (2026-07-17, `/goal` Phase 2): `scripts/optimusctl.sh backup` → `restore` into a scratch database with a real row-count match → tag `:previous` → deliberately break the running backend → confirm `/health` fails → `scripts/optimusctl.sh rollback` → confirm `/health` recovers. This closes an actual bug found while first writing this rehearsal: `optimusctl.sh` hardcoded the Docker image name prefix as `optimus-server`, which silently doesn't match in any checkout not literally named that (see `docs/context/KNOWN_ISSUES.md`) — now derived dynamically via `docker compose config --images`.

All of the above are already enforced in CI (`.github/workflows/ci.yml`) except the live `/health`/`/ready` schema-compatibility proof and the no-Scheduling-touched check, which are currently manual steps (see Follow-up below).

## Deployment checklist (the exact steps, in order)

This is the Phase 6 Part I deliverable: the concrete sequence for actually deploying a gate-verified commit, not just the gates themselves. **Every step below runs against real production/staging infrastructure and requires the owner's current-turn approval and real credentials before starting** — this document describes the steps precisely so they can be executed correctly when approved, it does not itself authorize running them.

1. **Backup.** `scripts/optimusctl.sh backup` against the live database before touching anything. Confirm the dump file was actually written (non-zero size, `ls -la backups/`) before proceeding — an empty or missing backup with no rollback path is worse than not deploying.
2. **Pull the exact commit.** `git fetch && git checkout <exact-commit-sha>` on the deploy target — not a branch name, not `main` as a moving pointer, the literal commit that passed every gate above. Record this SHA somewhere the rollback step can find it again (it's also what `/health`'s `git_commit` field will report once deployed, so it's independently verifiable after the fact).
3. **Build.** `GIT_COMMIT=$(git rev-parse HEAD) scripts/optimusctl.sh update` — this also tags the currently-running image as `:previous` before building the new one (`tag_current_as_previous`), which is what makes step 9's rollback possible; don't skip straight to a manual `docker compose build` that bypasses this tagging.
4. **Migrate.** `scripts/optimusctl.sh migrate` — run this as an explicit, separate step after the new image is built but as part of the same deploy window, not folded silently into container startup. This is also exactly the "app code briefly ahead of schema" window ADR-012 and the `behind`/`unmigrated` schema-compatibility states above are designed to tolerate — expect `/ready` to report `behind` for the few seconds between step 3 finishing and this step completing, not `unsupported`.
5. **Restart.** `scripts/optimusctl.sh update` already restarts `backend`/`worker`/`frontend` as its last action; since migrate needed to run first per this checklist's ordering, run `scripts/optimusctl.sh restart` again now so the running processes pick up the newly-migrated schema state cleanly rather than relying on them having already been serving traffic through the migration window.
6. **Health check.** `scripts/optimusctl.sh health` (or `curl -fsS <base-url>/health`) — confirm `version`/`git_commit` match exactly what step 2 checked out, not a cached or stale value.
7. **Readiness check.** `scripts/optimusctl.sh ready` (or `curl -fsS <base-url>/ready`) — confirm `status: "ready"` and `schema_compatibility: "matched"`. Do not proceed to step 8 while this reports anything other than `ready`/`matched`.
8. **Authenticated smoke test.** Run the Part C Playwright suite against the real deployed target (not the local dev stack) if the target's authentication and network topology allow it, or perform the equivalent manual pass by hand (real login, real customer/vehicle, at minimum viewing an existing invoice) — this is the step that would have caught, for example, the CSP violations documented in `KNOWN_ISSUES.md` that static checks alone missed.
9. **Rollback condition check.** See "Rollback criteria" below — if any of those conditions are true after steps 6-8, stop here and go to the rollback procedure instead of declaring the deploy done.
10. **Rollback command, if needed.** See "Rollback procedure" below.
11. **Post-deploy monitoring.** Per `docs/context/MONITORING.md`: confirm whatever external uptime checker/log destination/disk-alerting the owner has actually configured (if any) shows the new deploy as healthy. If none of those are configured yet, this step is watching `/health`/`/ready` and the structured logs by hand for a reasonable window after deploy — say so explicitly in the deploy record rather than silently skipping it.

## Rollback criteria

Roll back a deployed release if, after deploy:

- `/health` or `/ready` fails to return `200` within 5 minutes of step 5 (Restart) completing.
- `/ready` reports `schema_compatibility: "unsupported"` or `"unreachable"` and does not self-resolve within the expected `migrate` step window.
- The post-deploy authenticated smoke test (Part C's E2E suite, or a manual equivalent) fails on a path that passed against the previous release.
- Error-rate or log secret-scan alerting fires (once monitoring/alerting from Phase 6 Part H/I exists — not yet wired for staging as of this checklist).

## Rollback procedure

Use `scripts/optimusctl.sh rollback` (retags the previous image back to `:latest` and restarts) — already built and rehearsed once in Phase 5 (see `docs/context/PLANS.md`). If the rollback also requires a schema downgrade (a MAJOR-version release with a non-backward-compatible migration), use `scripts/optimusctl.sh migrate-down <revision>` **before** rolling the image back, so the older app version never runs against a newer schema it doesn't understand — the same `unsupported` classification above is what would catch this if the order were reversed, but the intent is not to depend on that safety net for an ordinary rollback.

## Follow-up not yet done

- Wire the live `/health`/`/ready` schema-compatibility proof above into a CI job (currently a manual step performed against a throwaway Docker Postgres/Redis pair).
- Wire the no-Scheduling-touched check into CI too (currently a manual `git diff`/`grep` step) — straightforward to automate as a workflow step comparing against the previous release tag once one exists.
- Automate release-notes generation from merged PRs (see `docs/RELEASE_NOTES.md` for the current manual version).
- Branch protection on `main` is still not enabled (tracked in `docs/context/PLANS.md` Phase 6 Part A) — a release-candidate tag currently has no CI-enforced guarantee that the tagged commit passed required checks beyond having been merged through the existing PR-gate discipline.
- The Deployment Checklist above has never been executed against real production/staging infrastructure end to end by this session — it's the documented, precise procedure, not evidence that a real deploy has been rehearsed on the actual droplet. `scripts/optimusctl.sh backup`/`restore`/`rollback` were rehearsed for real during Phase 6 Part H, but only against a local docker-compose stack, not staging (see `docs/context/PLANS.md`'s Part H entry for that evidence).
