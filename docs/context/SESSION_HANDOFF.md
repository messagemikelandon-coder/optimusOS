# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-10.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/KNOWN_ISSUES.md`, `git status`/`git log`, full local gate runs on 2026-07-10, a live Playwright check against the real backend (including CSP enforcement).

## Identity

- Updated UTC: 2026-07-10 (later in the day than the previous handoff).
- Agent: Claude
- Branch: `agent/claude/landing-page-redesign` (created off `main` at `ab8ed98`).
- Worktree: primary (`/home/dejake/optimus-server`); untracked stray `optimusOS/` clone still present (owner's accidental clone — leave alone, unrelated to this app).

## Active task — Landing page + full-app color/style redesign: IMPLEMENTED, uncommitted, pending review sign-off and owner approval

Owner goal (2026-07-10): add a new unauthenticated marketing landing page at `/` with working login access, shown before the authenticated dashboard ("OS system"); apply the same graphite/off-white/steel/restrained-red palette and existing 3D rotor/caliper/diagnostic-tablet motif consistently to the whole authenticated app (replacing the previous electric-blue palette). Full detail in `docs/context/CURRENT_STATE.md`'s "Landing Page Redesign" section — not duplicated here.

**Status**: implemented, all gates green (203 tests, ruff, pyright, node syntax), independently reviewed (one CRITICAL finding — an inline `<script>` that would have violated the app's `script-src 'self'` CSP and broken `/login`/`/approval` — found and fixed before this doc was written), and re-verified live against the real backend under the real CSP with zero violations. **Not committed, pushed, or deployed** — needs owner review/approval before any of that.

### What to check before continuing

- Read `docs/context/CURRENT_STATE.md`'s "Landing Page Redesign" section for the full change list, verification evidence, and what was intentionally left out (no authenticated-dashboard screenshot; no real field photography).
- Read `docs/context/KNOWN_ISSUES.md`'s newest "Historical Resolved Issues" entry for the two CSP violations found and fixed during this work (one introduced by this session, one pre-existing and unrelated).
- `git diff --stat` on this branch should show exactly four files: `app/static/index.html`, `app/static/styles.css`, `app/static/app.js`, `tests/test_official_ui.py`.
- The four running `docker compose` containers (`backend`, `frontend`, `postgres`, `redis`) are on the local dev stack; `backend` was rebuilt twice during this session to pick up the frontend changes for live CSP verification (its image bakes in `app/static` at build time — the `frontend` nginx service instead bind-mounts `app/static` live, which is why testing through nginx at `:5173` does not exercise the real CSP).

### Exact next task for this slice

Get explicit owner review/commit approval for this diff. If approved: commit (small, coherent commits — e.g. one for the CSP-safety fixes, one for the redesign itself, or bundle per owner preference), then decide push/PR/staging-deploy timing separately (none of that has owner approval yet either). If changes are requested, the branch is `agent/claude/landing-page-redesign` and is not shared with any other in-progress branch.

## Carried over from the previous (Phase 5.5) session — not touched by this slice

- Ask the owner to re-test the three staging bugs reported after the Phase 5.5 deploy (notifications reachable via mobile nav + desktop sidebar; estimate "Refresh status" button; Square tab visible in both nav surfaces) — this was the prior session's own open next-task and was not re-confirmed before this new slice started.
- Payment-schedule installment percentage split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`).
- No rate limiter on `POST /api/estimates`.
- Pre-existing work-order-completion commit-boundary race documented in `docs/context/KNOWN_ISSUES.md` (concurrent-race only, single-owner usage makes it near-impossible to hit).
- Square: email-TLD and phone-format validation gaps found during the real sandbox smoke test are non-blocking, no fix requested yet. Staging still has no Square credentials configured.
- The prior session's mobile-nav notifications-accessibility fix was never independently re-confirmed via a live authenticated browser session (blocked by the credential-materialization permission boundary at the time) — still worth asking the owner to confirm on next contact.
