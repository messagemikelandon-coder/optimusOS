---
name: project-sync
description: Loads a compact, current OptimusOS handoff from Git and the three canonical state files. Use at the start of every session or after another agent changes the branch.
disable-model-invocation: true
allowed-tools: Bash(git *), Bash(scripts/ai_context_snapshot.sh)
---
Run `${CLAUDE_PROJECT_DIR}/scripts/ai_context_snapshot.sh`.

Then report only:
1. branch and HEAD
2. clean/dirty worktree and unrelated changes
3. active task and owner
4. last verified gates
5. blockers and unverified checks
6. exact next task
7. no more than five files to read first

Do not begin implementation during this skill.
