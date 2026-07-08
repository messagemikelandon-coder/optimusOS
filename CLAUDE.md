@AGENTS.md

# OptimusOS — Claude Code Instructions

## Mission
Build OptimusOS into a reliable local-first mobile mechanic shop-management platform for Landon Motor Works, then prepare it for controlled staging and production. Do not skip local verification or deploy without Dejake's current-turn approval.

## Canonical truth
- Code, migrations, tests, and Git history are authoritative.
- Project state lives in `docs/context/CURRENT_STATE.md`, `KNOWN_ISSUES.md`, `SESSION_HANDOFF.md`, `ARCHITECTURE.md`, `PRODUCT.md`, and `PLANS.md`.
- The context manager and Claude auto-memory are supporting memory only. They must not override repository truth.
- Do not import every context document here. Load them through `/project-sync` to reduce startup tokens.

## Session startup
1. Run `/project-sync`.
2. Confirm branch, HEAD, worktree status, migration head, active task, blockers, and last verified gates.
3. Inspect only files relevant to the active task before broad exploration.
4. If another agent owns the branch or the handoff is stale, stop and report the conflict.

## Work loop
Use: inspect → plan → implement → focused tests → full gates → independent review → handoff.
- Maximum six subagents total.
- Maximum delegation depth one. Subagents must not spawn subagents.
- Maximum three repair passes for the same failing gate; after that, stop with evidence and a root-cause hypothesis.
- Use read-only agents for exploration, review, security, and release audits.
- Do not let the implementing agent grade its own work without an independent review.

## Git coordination
- One agent owns one branch/worktree at a time.
- Claude and Codex must never edit the same worktree concurrently.
- Do not reset, clean, force-push, rewrite history, discard unrelated changes, or modify another agent's uncommitted work.
- Do not commit, push, merge, open a PR, or deploy without explicit current-turn approval.
- End every completed work session with `/end-session`.

## Security
- Never read, print, modify, copy, or commit real `.env` files, credentials, tokens, private keys, session cookies, approval tokens, customer-sensitive data, or payment authorization details.
- Use `.env.example`, synthetic test data, mocks, and local containers.
- No live billable AI calls unless explicitly approved for that exact run.
- No production data mutation, public deployment, DNS, cloud credentials, payment integration, or destructive database operations without explicit approval.

## Required local gates
Use `/verify-local`. A code change is incomplete without executable evidence.

## Production boundary
Local completion does not equal production readiness. Production requires separate approval and evidence for staging, HTTPS, secrets, backups and restore, observability, rate limiting, migrations and rollback, dependency failure handling, security review, and deployment rollback.
