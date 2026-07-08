---
name: end-session
description: Produces the compact, evidence-based handoff that lets Codex or Claude resume OptimusOS without rereading chat history.
disable-model-invocation: true
---
Update `docs/context/SESSION_HANDOFF.md` using the repository template.

Required content:
- agent, branch, HEAD, worktree status
- bounded goal and status
- files/migrations/API changes
- exact commands and results
- independent review/security findings
- unverified and billable checks skipped
- unrelated preexisting changes
- blockers
- one exact next task
- no more than five fast-pickup files

Then run:

```bash
python scripts/check_ai_handoff.py
git status --short --branch
git diff --stat
git log -5 --oneline
```

Do not commit, push, merge, deploy, or claim production readiness.
