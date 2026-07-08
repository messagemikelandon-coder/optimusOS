# Known Issues

Purpose: confirmed defects, environment blockers, and their repair status.
Information owner: repository maintainers.
Read when: assessing current risk or planning repairs.
Update when: a defect is discovered, repaired, or reclassified.
Last verified date: 2026-07-08.
Relevant sources: `git status`, `git diff --stat`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`, `docker compose logs --tail=80 backend worker`, `docker compose exec -T backend alembic current`.

## Confirmed Open Issues

- None currently confirmed in the Work Order source implementation or automated verification path.

## Historical Resolved Issues

- Phase 1 closure verification items are resolved:
  - non-billable live Work Order proof passed against the Docker stack
  - independent review findings around blocked transitions, uncached estimate reopening, and note-recency ordering were fixed
  - security review of the Work Order diff completed with no findings
- Estimate Approval runtime defects and the `estimator_output_invalid` schema mismatch were resolved before the Work Order slice and remain closed; see Git history and prior session context for the detailed repair record.
