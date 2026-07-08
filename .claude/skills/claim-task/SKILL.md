---
name: claim-task
description: Claims one bounded OptimusOS task in the shared handoff and optionally a GitHub issue. Use only when Dejake explicitly assigns the task.
disable-model-invocation: true
argument-hint: "<task-name> [github-issue-number]"
---
Before claiming:
1. Run `/project-sync`.
2. Confirm no other agent owns the same branch/worktree.
3. Confirm the task is bounded with acceptance criteria.
4. Refuse to claim if the worktree contains unexplained changes.

Update `docs/context/SESSION_HANDOFF.md` with agent, branch, HEAD, goal, scope, owner, and status `active`.
If a GitHub issue number was supplied and `gh auth status` succeeds, update only assignment/status metadata; do not close, merge, or modify unrelated issue content.
Do not implement the task yet.
