# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-07.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/PLANS.md`, `docs/context/KNOWN_ISSUES.md`, `git status`.

## Identity

- Updated UTC: 2026-07-07T00:00Z
- Agent: Claude (this handoff); most recent commit on the branch was made by Codex
- Branch: `feat/estimate-approval` (renamed from `feat/vehicle-management`), ahead of `origin/feat/estimate-approval` by 1 commit (not pushed)
- HEAD: `c46d53f49f2010a9a7a1faa1b787db94c026e617` ("docs: update agent operating rules", authored by Codex)
- Origin HEAD: `ce3956199abe3443d8809cbb666cfa6a20032f2e` ("verify: complete estimate approval live proof") — this is the last commit confirmed pushed
- Worktree: primary (`/home/dejake/optimus-server`)
- Git status summary: `c46d53f` (Codex's `AGENTS.md` update) is committed locally but **not yet pushed**. Untracked: `.claude/agents/*.md` (6 files), `.claude/skills/*/SKILL.md` (6 files), `.github/workflows/ai-coordination.yml`, `CLAUDE.md`, `docs/context/AI_WORKFLOW.md`, `scripts/ai_context_snapshot.sh`, `scripts/check_ai_handoff.py` — the rest of the AI Coordination Pack that `c46d53f`'s `AGENTS.md` change references but that hasn't been committed yet.

## Active task

- Goal: Finish Phase 0 (freeze/backup of the Estimate Approval slice), then begin **Phase 1 — Work Orders**.
- Owner: unassigned (awaiting next session — Codex is the suggested owner per the roadmap in `docs/context/PLANS.md`)
- Status: **Estimate Approval slice is code-complete and fully live-verified (2026-07-06, real OpenAI call, full approval lifecycle including restart persistence). Phase 0 backup is ~90% done — see below for the exact remaining steps. Work Orders has not started.**
- Out of scope right now: Work Orders (do not start until Phase 0 is fully checked off in `docs/context/PLANS.md`); change-order / `waiting_for_approval` flow (status reserved in the enum for Phase 1 but not implemented until a later slice); a "revoked" approval-token status (deferred to Phase 6).

## Verified baseline

- Migration head: `006_estimate_approvals` (Work Orders will add `007_work_orders` — not yet created)
- Test count/result: `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` — 120 passed (as of the last full run, 2026-07-06)
- Local runtime state: `docker compose ps` was healthy (PostgreSQL, Redis, backend, worker, frontend) as of the last check. Re-verify with `/project-sync` before trusting this without a fresh check — time has passed and this environment may have changed outside this session's visibility (note: the last local commit, `c46d53f`, was made by Codex, not by the Claude session that wrote most of this file — confirm current state before proceeding).
- Last known good, pushed commit: `ce39561` on `feat/estimate-approval`

## The roadmap

**Read `docs/context/PLANS.md` before doing anything else.** It is the full phase-by-phase roadmap (Phase 0 through Phase 6: Work Orders → Invoices/PDF → Payments → Local MVP hardening → Staging → Production) with acceptance criteria, required tests, agent assignments, stop conditions, and the GitHub workflow. This handoff file only tracks the immediate next steps; `PLANS.md` is the durable reference so no future session re-derives the sequence.

## Immediate next steps (Phase 0 completion)

1. Push the current branch and confirm the remote matches:
   ```bash
   git push origin feat/estimate-approval
   git rev-parse HEAD
   git rev-parse origin/feat/estimate-approval
   ```
   (Requires your explicit approval before pushing — do not push automatically.)
2. Decide the fate of the untracked AI Coordination Pack files listed above. Recommendation from the roadmap: commit them as their own clearly-labeled commit (e.g. `chore: add AI coordination pack`) rather than leaving them untracked indefinitely — but this needs your explicit sign-off on the exact file list first, same as every commit this project has made.
3. Update `docs/context/PLANS.md`'s Phase 0 checklist to reflect the above once done.
4. Only then: begin Phase 1 (Work Orders) on a new branch `feat/work-orders` created from `feat/estimate-approval`.

## Unverified

- Current live Docker/git state has not been re-confirmed by this session after Codex's `c46d53f` commit — re-run `/project-sync` at the start of the next session rather than trusting this file's "Verified baseline" section blindly.
- Token usage and estimated cost for OpenAI calls made during the Estimate Approval live proofs: still not available (no usage logging exists in the application).
- Production/staging checks not run (expected — blocked until Phase 4 per `PLANS.md`).

## Unrelated preexisting changes

- The AI Coordination Pack (`AGENTS.md`'s agent-operating-rules section, `.claude/`, `.github/`, `CLAUDE.md`, `docs/context/AI_WORKFLOW.md`, `scripts/ai_context_snapshot.sh`, `scripts/check_ai_handoff.py`) is the coordination-workflow infrastructure this whole roadmap runs on top of — not a code change to the product itself. See "Immediate next steps" above for what to do with it.

## Blockers and risks

1. Local HEAD (`c46d53f`) is not yet pushed — this is the first Phase 0 backup gap to close.
2. No "revoked" approval-token status or revoke endpoint exists yet (only `active`, `expired`, `used`) — deferred to Phase 6 per `PLANS.md`, not a regression.
3. Live AI web-research parts lookup can still legitimately return no priced parts for some vehicle/job combinations — inherent variability observed during the Estimate Approval live proofs, not a defect, and not specific to Work Orders.
4. Minor log-hygiene item from an earlier, superseded failure path (verbose Pydantic serialization warnings echoing research-text fragments) remains unaddressed, out of scope.

## Exact next task

Complete Phase 0 (push + AI Coordination Pack decision, both requiring explicit approval first), update `PLANS.md`'s checklist, then begin Phase 1 — Work Orders exactly as scoped in `docs/context/PLANS.md`: new branch `feat/work-orders`, read-only exploration of the estimate/revision/approval models first, a bounded implementation plan presented for approval before any code is written, then the full backend + frontend + 14 required test categories + non-billable runtime proof + independent review + security review + docs update. No live OpenAI calls needed for this slice. Do not commit, push, or start Phase 2 without explicit approval at each step.

## Fast pickup

Read only these files first:
1. `docs/context/PLANS.md` (the roadmap — read this in full)
2. `docs/context/CURRENT_STATE.md`
3. `app/estimate_store.py` (the pattern to follow for Work Orders: ownership scoping, status handling, revision snapshots)
