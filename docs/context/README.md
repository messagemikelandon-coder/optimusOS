# Context Management

Purpose: durable routing and freshness policy for repository context.
Information owner: repository maintainers and Codex session authors.
Read when: before deciding which project context file to load or update.
Update when: the context system structure, freshness rules, or routing rules change.
Last verified date: 2026-07-01.
Relevant sources: `AGENTS.md`, `docs/frontend-audit.md`, `docs/ui-control-matrix.md`, `scripts/optimusctl.sh`, `app/main.py`.

## Index

- [CURRENT_STATE.md](./CURRENT_STATE.md) for live operational status.
- [SESSION_HANDOFF.md](./SESSION_HANDOFF.md) for the handoff template used between sessions.
- [ARCHITECTURE.md](./ARCHITECTURE.md) for the verified current architecture.
- [DECISIONS.md](./DECISIONS.md) for durable architecture decisions.
- [PRODUCT.md](./PRODUCT.md) for verified product scope.
- [BUSINESS_RULES.md](./BUSINESS_RULES.md) for owner and customer workflow rules.
- [SECURITY.md](./SECURITY.md) for secret-handling and auth boundaries.
- [KNOWN_ISSUES.md](./KNOWN_ISSUES.md) for confirmed defects or environment blockers.
- [GLOSSARY.md](./GLOSSARY.md) for shared project terms.
- [ROADMAP.md](./ROADMAP.md) for ordered work phases.

## Context Freshness Checklist

Check each statement before adding or keeping it:

- Is the statement still true?
- Is there source evidence?
- Is it duplicated elsewhere?
- Is it a rule, decision, current state, or temporary handoff?
- Does it contain sensitive information?
- Does another document now supersede it?
- Is the last-verified date still credible?

## Freshness Rules

- `CURRENT_STATE.md` is replaced or corrected as state changes.
- `SESSION_HANDOFF.md` is replaced after each substantial session.
- `DECISIONS.md` is append-oriented, but decisions may be marked superseded.
- `KNOWN_ISSUES.md` must reflect actual issue status.
- `PRODUCT.md` and `BUSINESS_RULES.md` change only when product or owner rules change.
- `AGENTS.md` remains concise and mandatory.
- Logs and raw terminal transcripts do not belong in permanent context.

## Optional Codex Memories

Codex Memories are optional local recall, not the project source of truth.

- Required rules remain in `AGENTS.md` and checked-in documentation.
- Memories must not be treated as the sole source of project truth.
- Secret values must not be deliberately stored in memory.
- `/memories` can control memory behavior for a thread.
