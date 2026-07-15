# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-15.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/KNOWN_ISSUES.md`, `docs/context/PLANS.md`, `git log`/`git status`, `gh pr list --state merged`, a full local gate run plus a live proof against a throwaway Postgres/Redis pair.

## Identity

- Updated UTC: 2026-07-15.
- Agent: Claude.
- `main` HEAD: `abbba44` (merge of PR #32). Verified via `git fetch origin main`.
- Worktree used this session: `.claude/worktrees/release-process`, branch `agent/claude/release-process` (renamed from the auto-generated `worktree-release-process` before pushing, to follow `AGENTS.md`'s branch-naming convention). Clean after merge; not deleted (`gh pr merge --delete-branch=false`).

## Active task

Phase 6 Part J — release process infrastructure, owner-directed (semver, machine-readable app version, deployed version shown in the System UI, migration head + source commit recorded, release notes from merged work, a release checklist, a release-candidate branch/tag convention, all CI gates required before release, rollback criteria, database migration compatibility documented, and the app prevented from reporting itself ready against an unsupported database schema). **Done and merged via PR #32.**

- `app/__init__.py::__version__` bumped `7.0.1` → `7.1.0`; `pyproject.toml` and every other hardcoded version-string duplicate found in the repo (`app/services/http.py`, `integration/optimus_adapter.py`, `app/static/index.html`'s marketing footer, `tests/test_official_ui.py`) now derive from it, with `tests/test_release.py::test_pyproject_version_matches_app_version` preventing future drift.
- New `app/migration_compat.py`: dialect-agnostic schema-compatibility check (`matched`/`behind`/`unmigrated`/`unsupported`/`unreachable`). Only `unsupported`/`unreachable` block readiness — `behind`/`unmigrated` are tolerated by design, since `scripts/optimusctl.sh update` runs before `migrate` in the documented deploy runbook. Recorded as ADR-012 in `docs/context/DECISIONS.md`.
- `/health` and `/ready` now report `version`, `git_commit` (baked into the Docker image at build time via a new `GIT_COMMIT` build arg on `backend`/`worker` in `docker-compose.yml`/`Dockerfile`), and `migration_head`; `/ready` additionally reports `database_migration_revision` and `schema_compatibility`, degrading `status` to `"degraded"` (not crashing) when unsafe.
- System bay UI gained a "Build" tile (`app/static/index.html`'s `runtime-grid`, populated by `app/static/app.js`) showing the running migration head and commit.
- New `docs/context/RELEASE_CHECKLIST.md` (versioning scheme, required gates, rollback criteria/procedure, release-candidate branch/tag convention: `vMAJOR.MINOR.PATCH` tags, `release/vMAJOR.MINOR.x` branches) and `docs/RELEASE_NOTES.md` (first formal entry, 7.1.0, summarizing PRs #27-#31 plus this work).
- `docs/context/PLANS.md` Phase 6 gained a Part J entry; `docs/context/DECISIONS.md` gained ADR-012.
- **No git tag was created and nothing was deployed** — per the owner's explicit constraint that this requires separate approval.

## Verified this session

- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check .` → clean.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` → all checks passed.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright` → 0 errors, 0 warnings.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` → full suite green, including 8 new tests (`tests/test_migration_compat.py` ×6, `tests/test_release.py` ×2) and extended `/health`/`/ready` coverage in `tests/test_api.py`.
- `node --check app/static/app.js` (and every other non-vendor static JS file) → OK.
- **Live proof against real infrastructure** (not just unit tests): started throwaway Postgres + Redis containers, ran `alembic upgrade head`, ran the real app via `uvicorn` with `GIT_COMMIT` set to the real commit SHA. `/health` returned the real commit and `migration_head: "018_approval_token_revocation"`; `/ready` returned `schema_compatibility: "matched"`, `status: "ready"`. Confirmed the served `index.html` contains the new Build tile with DOM ids (`#system-migration-head`, `#system-git-commit`) exactly matching what `app.js` populates. Throwaway containers and server process cleaned up afterward.
- CI on PR #32: all 5 checks passed (`lint-typecheck-test`, `migrations`, `docker-compose-integration`/build+boot+secret-scan, the authenticated E2E job, `handoff-contract`).
- Merged to `main` via PR #32 (`gh pr merge --merge --delete-branch=false abbba44`) — owner explicitly approved merging without human code review, same pattern as prior PRs this session.

## Unverified / not done this session

- No live/billable OpenAI calls were made.
- The live `/health`/`/ready` schema-compatibility proof is still a manual step, not wired into CI (tracked as a RELEASE_CHECKLIST.md follow-up).
- No release tag was cut and nothing was deployed to staging or production — both require separate explicit owner approval and were out of scope for this task.
- Branch protection on `main` is still not enabled (pre-existing gap, tracked in `docs/context/PLANS.md` Phase 6 Part A).

## Unrelated preexisting changes

- Untracked stray `optimusOS/` directory at the repo root — predates every session on record, not part of any commit, still present, still "leave alone" per every prior handoff.

## Blockers and risks

- None blocking.

## Exact next task

Per the owner's approved roadmap (`docs/context/PLANS.md` Phase 6), the largest remaining open items are:

- **Part D/E** — Diagnostics/Inspections auditability (archive/void + audit trail) and the technician workflow carve-out for those modules.
- **Part F** — Parts/Vendors purchase-order + allocation workflow (Sub-phase 3 shipped only a vendor directory + inventory reorder flag).
- **Part G** — Reports completion (payment-activity, technician-time, commission reports; Sub-phase 7 shipped a read-only reuse of existing dashboard/invoice endpoints only).
- **Part H remainder** — threat model, full security-event taxonomy, OpenAI usage/cost logging, customer-data retention/export/deletion policy, and monitoring/alerting requirements (approval-token revocation, multi-instance rate limiting, and structured logging are already done).
- **Part I** — staging verification + deployment checklist, including catching the staging droplet up to current `main` (it is still behind, missing PR #22 and everything after).

None of these are started. Pick one with the owner before beginning — do not assume ordering beyond the dependency notes already in `docs/context/PLANS.md`.

## Carried over from prior sessions — not touched by this session

- Ask the owner to re-test the three staging bugs reported after the Phase 5.5 deploy (notifications reachable via mobile nav + desktop sidebar; estimate "Refresh status" button; Square tab visible in both nav surfaces) — still the oldest open follow-up, not yet re-confirmed.
- Payment-schedule installment percentage split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`).
- Pre-existing work-order-completion commit-boundary race documented in `docs/context/KNOWN_ISSUES.md` (concurrent-race only, single-owner usage makes it near-impossible to hit).
- Square: email-TLD and phone-format validation gaps found during an earlier sandbox smoke test are non-blocking, no fix requested yet. Staging still has no Square credentials configured.
- No `optimus-security-reviewer` pass has been run against Phase 5.6 sub-phases 3, 4, 6, 7 (Vendors+Parts, Service Desk, Diagnostics+Inspections, Reports) — only sub-phases 1, 2, and 5 (Scheduling) have had one. Worth closing before Phase 6 Part E gives technicians write access to Diagnostics/Inspections.
- The staging droplet is still behind current `main` (last confirmed after PR #21, before PR #22/#23, and now several more PRs behind that). Catching it up is a deploy action requiring explicit current-turn approval.
