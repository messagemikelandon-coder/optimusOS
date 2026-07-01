# Known Issues

Purpose: confirmed defects, environment blockers, and their repair status.
Information owner: repository maintainers.
Read when: assessing current risk or planning repairs.
Update when: a defect is discovered, repaired, or reclassified.
Last verified date: 2026-07-01.
Relevant sources: `docs/frontend-audit.md`, `docs/UI_CONNECTION_AUDIT.md`, `docs/UBUNTU_DEPLOYMENT_REPORT.md`, `git status`, `git diff --stat`.

## Confirmed Open Issues

No confirmed open application defects were identified during the current repository audit.

## Environment Blocker

- ID: ENV-001
- Priority: Medium
- Status: Open
- Description: The Codex sandbox blocked fresh socket-based live-stack checks during this documentation session.
- Evidence: `scripts/optimusctl.sh status`, `scripts/optimusctl.sh health`, and `scripts/optimusctl.sh ready` could not complete in the sandbox because socket access was denied.
- Root cause if known: sandbox networking restriction, not a repository defect.
- Affected files: none.
- Workaround: rely on the last verified live-stack reports in `docs/frontend-audit.md` and `docs/UBUNTU_DEPLOYMENT_REPORT.md` until a runnable environment is available.
- Required repair: none in the repository; rerun live checks in an environment with socket access.
- Required regression test: none.
- Related Linear or GitHub issue: not available.
