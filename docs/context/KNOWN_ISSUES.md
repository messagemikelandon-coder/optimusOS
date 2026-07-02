# Known Issues

Purpose: confirmed defects, environment blockers, and their repair status.
Information owner: repository maintainers.
Read when: assessing current risk or planning repairs.
Update when: a defect is discovered, repaired, or reclassified.
Last verified date: 2026-07-02.
Relevant sources: `git status`, `git diff --stat`, `app/auth.py`, `app/context_store.py`, `app/main.py`, `tests/test_context_api.py`, `docker compose ps`, `docker compose logs --tail=200 backend worker`, `curl http://127.0.0.1:8000/ready`.

## Confirmed Open Issues

- None currently confirmed in the authenticated/context/customer baseline.

## Deferred Verification Notes

- Billable live chat and estimate calls were intentionally skipped in this session because they may spend money through OpenAI-backed requests. This is a verification gap, not a confirmed defect.
- The Customer slice is verified for backend and frontend authenticated flows, but Vehicles and downstream business records are intentionally not started yet.
