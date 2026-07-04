# Known Issues

Purpose: confirmed defects, environment blockers, and their repair status.
Information owner: repository maintainers.
Read when: assessing current risk or planning repairs.
Update when: a defect is discovered, repaired, or reclassified.
Last verified date: 2026-07-04.
Relevant sources: `git status`, `git diff --stat`, `app/auth.py`, `app/context_store.py`, `app/main.py`, `tests/test_context_api.py`, `docker compose ps`, `docker compose logs --tail=200 backend worker`, `curl http://127.0.0.1:8000/ready`.

## Confirmed Open Issues

- None currently confirmed in the authenticated/context/customer baseline.

## Recently Resolved (2026-07-04, Estimate Approval repair)

A controlled live proof of the Estimate Approval slice found three confirmed defects, repaired this session and verified with a non-billable Playwright run against the rebuilt Docker stack (exit code 0, run twice) plus 120 passing pytest tests:

- **Approval link routing**: `navigate()` in `app/static/app.js` cleared `window.location.hash` when switching to the approval view, so generated `/approval#token=...` links resolved to `/` on direct navigation and on refresh. Fixed by preserving the hash in the `history.replaceState` call. Regression introduced in commit `d162a55`.
- **Public approval-view data exposure**: `POST /api/estimate-approval/view` (unauthenticated, token-scoped) returned the full internal estimate/research payload, including unselected competitor part options/pricing, internal labor reasoning, and raw rate/fee overrides, to anyone holding a valid approval link. Fixed by adding narrow customer-safe response models (`EstimateApprovalPublicView` and related, in `app/models.py`) and wiring them into `get_approval_view()` in `app/estimate_store.py`. Confirmed by field-by-field review and a payload-shape regression test.
- **Fabricated zero-hour labor line**: `_validate_generated_estimate()` in `app/estimate_store.py` only rejected an estimate when both labor and parts were hollow, so a non-empty `labor_items` list whose lines all collapsed to zero hours/total could pass validation next to real parts pricing, showing the customer a nonsense free-labor line. Tightened to reject that case while still accepting legitimate labor-optional (parts-only) and parts-optional (labor-only) jobs.

A fourth suspected defect (one generation action allegedly triggering two OpenAI Responses API calls) was investigated and found to already be handled correctly by the existing model-fallback loop in `app/services/openai_web.py` (retries only on genuine model-unavailability). Closed with new regression tests proving call counts; no production code change was needed.

## Deferred Verification Notes

- Billable live chat and saved-estimate generation calls were intentionally skipped in this session because they may spend money through OpenAI-backed requests. This is a verification gap, not a confirmed defect.
- The Estimate Approval slice is source-backed, locally tested, and deployed to the live schema, but the billable live browser proof for estimate creation, approval-link generation, and customer approval remains intentionally deferred pending explicit owner approval.
- No "revoked" approval-token status or revoke endpoint exists yet (only `active`, `expired`, `used`). Identified during this session's repair as a real, intentionally deferred gap — not implemented because it was out of the bounded scope of the four defects above.
