# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-17.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/PLANS.md`, `git log`/`git status`, a full local gate run plus a live proof against a real docker-compose-managed Postgres + Redis, the real Part C Playwright e2e suite.

## Identity

- Updated UTC: 2026-07-17.
- Agent: Claude.
- `main` HEAD: `a13a68d` (merge of PR #44, Phase 6 Part H — threat model, security-event logging, OpenAI cost logging, policy docs).
- Worktree used this session: `.claude/worktrees/release-process`, branch `agent/claude/staging-verification`, branched fresh from `origin/main`. Not yet committed, pushed, or opened as a PR.

## Active task

Phase 6 Part I (staging verification) — the second half of the owner's explicit instruction "complete H and I, then tell me what is left to complete the goal." Part H merged earlier this session (PR #44). **Everything Part I calls for that's achievable without touching real staging infrastructure is done, live-verified, and documented; not yet committed, pushed, or merged.**

- Ran the full gate suite for real against the exact merged Part H commit: `ruff`/`pyright`/`pytest`/`node --check` all clean; a real `docker compose build` of backend/worker; a genuinely fresh Postgres migrated to a single linear head; `/health`/`/ready` confirmed the exact commit and `schema_compatibility: "matched"`; a real log-secret scan found nothing; the real Part C Playwright e2e suite (3 tests) passed; the customer-facing HTML/PDF field-exclusion test passed; confirmed zero Scheduling code touched across this entire session's diff range.
- Extended `docs/context/RELEASE_CHECKLIST.md` (rather than creating a new document) with the missing Part I gate items and a new, concrete 11-step ordered Deployment Checklist section.
- Full detail, including a real environment quirk hit and worked around during the rehearsal (this app's `.env`-over-shell-env precedence design silently defeating a test fixture's env var override), in `docs/context/PLANS.md`'s Part I entry.

## What's explicitly NOT done, and why

Per `CLAUDE.md`'s Production boundary — this was never in scope for Part I regardless of session progress:

- **Catching the real staging droplet up to current `main` was not attempted.** This is explicitly named as a separate action in `docs/context/PLANS.md`'s own Part I entry ("does not require any of Parts A-H and can happen independently once approved") — it needs the owner's current-turn approval and real droplet credentials, neither of which this session has or went looking for.
- Everything else Part I calls for (gates, the deployment checklist document, the Playwright smoke test, the log scan) is genuinely complete — this isn't a partial-credit situation, just a hard boundary between "verify the process is correct and documented" and "execute it against a real production target."

## Verified baseline

- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check .` → clean.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .` → all checks passed.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright` → 0 errors, 0 warnings.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q -rA` → 387 passed, 2 skipped (pre-existing, unrelated — needs a real local Redis), 0 failed.
- `node --check app/static/app.js` → OK.
- This is a documentation-only diff (`docs/context/PLANS.md`, `docs/context/RELEASE_CHECKLIST.md`, this file) — no application code changed, so the above are unchanged from Part H's already-verified baseline, re-confirmed rather than assumed stale.

## Evidence

- **Real `docker compose build backend worker`** succeeded against the exact Part H merge commit, using a throwaway local `.env` (placeholder values only, deleted afterward).
- **A genuinely fresh Postgres** (new container, no prior state) reached `alembic heads` → exactly one head (`021_part_allocations`) via the real built backend image running `alembic upgrade head`, not a shortcut.
- **`/health` and `/ready`**, hit directly against the backend container's Docker-network IP (another unrelated project already held the usual `8000`/`5173` host ports this app's `docker-compose.yml` normally publishes, during this session — worked around without touching that other project's containers), confirmed the exact commit SHA and migration head, with `schema_compatibility: "matched"`.
- **A real `python -m scripts.scan_logs_for_secrets --project release-process --services backend worker`** scan of the real container's boot logs found nothing.
- **The real Part C authenticated Playwright suite** (`tests/e2e/`, 3 tests, its own separately-managed real browser/Postgres/session stack) passed.
- **A real environment quirk was hit and fixed during this rehearsal, not a code bug**: a leftover throwaway `.env` from earlier in the same rehearsal (pointing `DATABASE_URL` at a since-torn-down container IP) broke the Playwright suite's own fixture on the first attempt, because this app deliberately makes its `.env` file take precedence over shell-exported environment variables (by design, per an existing code comment). Fixed by deleting the stale `.env` before rerunning.
- All containers, volumes, networks, and Docker images created for this rehearsal were torn down afterward; the worktree is clean (`git status --short` shows only the intended doc changes).

## Unverified

- Not committed, pushed, opened as a PR, or merged — awaiting the next step in this same task.
- No independent review has run on this diff yet (it's documentation-only, but this repo's own discipline calls for an independent pass before merge regardless — do that next, before asking for commit approval).
- CI has not yet run against this branch (no PR opened yet).

## Unrelated preexisting changes

- Untracked stray `optimusOS/` directory at the repo root — predates every session on record, not part of any commit, still present, still "leave alone" per every prior handoff.
- Another, unrelated project's Docker containers (`optimus-server-backend-1` et al., 23+ hours uptime, holding host ports `8000`/`5173`) were observed running during this session's local rehearsal — not touched, not stopped, not investigated further than confirming they belong to a different compose project.

## Blockers and risks

- None blocking the work in this diff. The one explicitly-not-done item (catching the staging droplet up to `main`) is blocked on the owner's credentials/approval, not on anything this session could have done differently.

## Exact next task

Launch an independent review of this diff (docs-only, but still due one per this repo's standing discipline), then get explicit current-turn owner approval, commit, push `agent/claude/staging-verification`, open a PR, verify CI, and merge with explicit approval (same pattern as PRs #38-44 this session).

**After that PR merges, Part I is complete, and so is the owner's original "complete H and I" instruction.** The next message to the owner should be the "what is left to complete the goal" summary they explicitly asked for — at minimum:

- **Catching the staging droplet up to current `main`** — a real deploy action, needs the owner's credentials and current-turn approval; the exact steps are now documented in `docs/context/RELEASE_CHECKLIST.md`'s new Deployment Checklist section.
- **Three concrete monitoring decisions** named in `docs/context/MONITORING.md` (external uptime checker, log-aggregation destination, disk-space alerting) — none configured yet.
- **The real customer-data deletion feature** described but not built in `docs/context/DATA_RETENTION.md` — needs the owner's answer to the three policy questions posed there.
- **Report scheduling/delivery** — explicitly deferred out of Phase 6 Part G from its very first slice, never picked up.
- **Diagnostic/inspection findings' report already shipped** (Part G Slice 5) but the broader "Diagnostic/Inspection" module itself has never had an `optimus-security-reviewer` pass, per the carried-over item below — worth flagging given Part H's own diff touched auth/rate-limiting directly this session.
- The **owner-only pilot → controlled customer pilot** step named at the top of `docs/context/PLANS.md`'s Phase 6 section, which sits after Parts A-J and has not been started.

## Carried over from prior sessions — not touched by this session

- Ask the owner to re-test the three staging bugs reported after the Phase 5.5 deploy (notifications reachable via mobile nav + desktop sidebar; estimate "Refresh status" button; Square tab visible in both nav surfaces) — still the oldest open follow-up, not yet re-confirmed.
- Payment-schedule installment percentage split remains an owner-confirmed placeholder (`docs/context/BUSINESS_RULES.md`).
- Pre-existing work-order-completion commit-boundary race documented in `docs/context/KNOWN_ISSUES.md` (concurrent-race only, single-owner usage makes it near-impossible to hit).
- Square: email-TLD and phone-format validation gaps found during an earlier sandbox smoke test are non-blocking, no fix requested yet. Staging still has no Square credentials configured.
- No `optimus-security-reviewer` pass has been run against Phase 5.6 sub-phases 3, 4, 6, 7 (Vendors+Parts, Service Desk, Diagnostics+Inspections, Reports), or against Phase 6 Parts D/E/F/G/H — only sub-phases 1, 2, and 5 (Scheduling) have had one.
- The staging droplet is still behind current `main`. Catching it up is a deploy action requiring explicit current-turn approval and real credentials this session does not have.
