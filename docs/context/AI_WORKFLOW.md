# OptimusOS Two-Agent Workflow

## Purpose
Claude Code and Codex complement each other, but Git—not chat—is the synchronization layer.

## Recommended division of labor

### Claude Code
Best assigned to:
- repo-wide exploration and architecture mapping
- specifications and implementation plans
- root-cause investigation across many files
- adversarial code/security review
- UI/UX critique and browser-driven validation
- production-readiness audits and documentation coherence

### Codex
Best assigned to:
- bounded implementation from an approved specification
- precise edits and refactors
- repetitive test repair and terminal verification
- migration/API implementation with explicit acceptance criteria
- patch-focused follow-up work

This is a default, not a hard product limitation. Assign by task and always require independent verification.

## Branch and worktree discipline

Do not use both agents as writers in one worktree.

Example only after the current branch is safely backed up:

```bash
# Integration worktree remains the source used by Dejake.
git worktree add ../optimus-claude -b agent/claude/estimate-approval-repair HEAD
git worktree add ../optimus-codex -b agent/codex/review-estimate-approval HEAD
```

One branch implements; the other reviews committed changes or a PR. Do not independently implement the same task unless running a deliberate comparison experiment.

## GitHub task ledger

Use one GitHub issue per bounded slice. Suggested labels:
- `agent:claude`
- `agent:codex`
- `status:ready`
- `status:active`
- `status:blocked`
- `status:review`
- `area:backend`
- `area:frontend`
- `area:security`
- `area:production`

Issue body:
- goal
- current baseline
- in scope
- out of scope
- acceptance tests
- owner branch
- dependencies

PR body:
- issue
- implementation summary
- files/migrations/API changes
- commands and results
- screenshots where relevant
- risks and rollback
- handoff document updated

## Low-token pickup protocol

At the start of a session, load only:
1. `AGENTS.md` through the tool's native mechanism
2. `CLAUDE.md` for Claude
3. `docs/context/SESSION_HANDOFF.md`
4. `docs/context/CURRENT_STATE.md`
5. `docs/context/KNOWN_ISSUES.md`
6. `git status`, last five commits, and the focused diff

Read architecture/product documents only when the task requires them. Do not paste entire chat histories into either tool.

## Session end protocol

1. Run focused checks.
2. Run full required gates when implementation is complete.
3. Request an independent reviewer/security agent.
4. Update the handoff and current-state documents only with verified facts.
5. Record unverified and billable checks explicitly.
6. Leave the worktree in a known state and report `git status --short`.
