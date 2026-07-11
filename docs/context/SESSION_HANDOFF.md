# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-11.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/KNOWN_ISSUES.md`, `git status`/`git log`, full local gate runs on 2026-07-11, a live Playwright check against the real backend under a synthetic authenticated session (including CSP enforcement).

## Identity

- Updated UTC: 2026-07-11.
- Agent: Claude
- Branch: `agent/claude/landing-page-redesign` (created off `main` at `ab8ed98`).
- Worktree: primary (`/home/dejake/optimus-server`); untracked stray `optimusOS/` clone still present (owner's accidental clone — leave alone, unrelated to this app).

## Active task — Two slices on one branch: IMPLEMENTED, uncommitted, pending review sign-off and owner approval

This branch now carries two related, independently-implemented pieces of work, both detailed in full in `docs/context/CURRENT_STATE.md` (not duplicated here):

1. **Landing Page Redesign** — a new unauthenticated marketing page at `/` plus a graphite/off-white/steel/restrained-red re-theme of the whole app.
2. **Overview Dashboard & Approval Queue** — replaced the old "Shop intelligence online" dashboard hero with a real, backend-connected shop-management overview (metric cards, gauges, Chart.js trend charts, revenue breakdown, rule-based Shop Insights, current-operations/financial-obligations panels) plus a new real Approval Queue view. Built from an owner-approved plan (via `/plan`-style review) after a full repo audit. No fabricated data anywhere — metrics without real backing (Gross Profit, Net Profit, Technician/Bay Utilization) show an honest "not available" reason instead.

**Status**: both slices implemented, all gates green (210 tests, ruff, pyright, node syntax), independently reviewed where applicable, and live-verified against the real backend under its real CSP with zero violations. **Not committed, pushed, or deployed** — needs owner review/approval before any of that.

### What to check before continuing

- Read `docs/context/CURRENT_STATE.md`'s "Landing Page Redesign" and "Overview Dashboard & Approval Queue" sections for full change lists and verification evidence.
- Read `docs/context/KNOWN_ISSUES.md`'s three newest "Historical Resolved Issues" entries: two CSP violations (landing-page work) and one Chart.js layout bug (dashboard work) — all found and fixed during this branch's own live verification, not pre-existing regressions.
- `git status --short` should show: `app/dashboard_store.py` and `app/static/vendor/` as new (untracked), and `app/main.py`, `app/models.py`, `app/static/{app.js,index.html,styles.css}`, `tests/test_official_ui.py`, `docs/context/*.md` as modified, plus new `tests/test_dashboard_api.py`.
- The four `docker compose` containers (`backend`, `frontend`, `postgres`, `redis`, `worker`) are running the local dev stack; `backend` was rebuilt several times during this session (its image bakes in `app/static` and `app/*.py` at build time — the `frontend` nginx service instead bind-mounts `app/static` live, which is why testing purely through nginx at `:5173` never exercises the real CSP). The backend image is currently a clean build of the final committed-ready source (no leftover temp verification scripts).
- No synthetic or real credentials are left lying around: the synthetic `dashboard-verify-*` owner created for live dashboard verification, and all its seeded data, were deleted from the dev database afterward via cascade delete.

### Exact next task for this branch

Get explicit owner review/commit approval for both slices (can be reviewed/committed together or separately — they touch mostly non-overlapping files except `app/static/index.html`/`styles.css`/`app.js`, which both slices edit). If approved: commit (logical commits per slice recommended), then decide push/PR/staging-deploy timing separately (no approval for that yet either). If changes are requested, the branch is `agent/claude/landing-page-redesign` and is not shared with any other in-progress branch.

## Carried over from the Phase 5.5 session — not touched by either slice on this branch

- Ask the owner to re-test the three staging bugs reported after the Phase 5.5 deploy (notifications reachable via mobile nav + desktop sidebar; estimate "Refresh status" button; Square tab visible in both nav surfaces) — still the oldest open follow-up, not yet re-confirmed.
- Payment-schedule installment percentage split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`).
- No rate limiter on `POST /api/estimates`.
- Pre-existing work-order-completion commit-boundary race documented in `docs/context/KNOWN_ISSUES.md` (concurrent-race only, single-owner usage makes it near-impossible to hit).
- Square: email-TLD and phone-format validation gaps found during the real sandbox smoke test are non-blocking, no fix requested yet. Staging still has no Square credentials configured.
