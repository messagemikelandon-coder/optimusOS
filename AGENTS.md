# Agent Instructions

## Project identity

- OptimusOS supports Landon Motor Works.
- Optimus is the owner-facing management agent.
- FastAPI remains the backend unless an approved architecture decision says otherwise.
- The browser must never receive OpenAI or other server API keys.

## Mandatory Reading

Before every task, read:

- `docs/context/CURRENT_STATE.md`
- `docs/context/SESSION_HANDOFF.md`

For architecture tasks, also read:

- `docs/context/ARCHITECTURE.md`
- `docs/context/DECISIONS.md`

For business workflow tasks, also read:

- `docs/context/PRODUCT.md`
- `docs/context/BUSINESS_RULES.md`

For authentication, API, deployment, or data tasks, also read:

- `docs/context/SECURITY.md`

For backend implementation or debugging, also read:

- `app/AGENTS.md` if present

For frontend work, also read:

- `docs/frontend-audit.md`
- `docs/ui-control-matrix.md`

## Working Rules

- Inspect before editing.
- Identify the root cause.
- Make the smallest coherent change.
- Do not edit generated dist files.
- Do not hardcode credentials.
- Do not expose secrets.
- Do not weaken authentication.
- Do not bypass approval controls.
- Do not silently replace working architecture.
- Add regression tests for repaired defects.
- Review the Git diff before committing.
- Do not claim completion based only on static inspection.
- Do not work directly on `main`.

## Quality Gates

Where applicable, run:

```bash
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format .
env UV_CACHE_DIR=/tmp/uv-cache uv run ruff check .
env UV_CACHE_DIR=/tmp/uv-cache uv run pyright
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -vv --durations=20
```

Also run applicable frontend lint, typecheck, build, and Playwright commands.

## Context Update Rules

At the end of any substantial task:

1. Update `docs/context/CURRENT_STATE.md` when project status changed.
2. Update `docs/context/DECISIONS.md` when an architectural decision was made.
3. Update `docs/context/KNOWN_ISSUES.md` when defects were discovered or resolved.
4. Replace `docs/context/SESSION_HANDOFF.md` with a concise current handoff.
5. Do not store transient terminal output in permanent context.
6. Do not store passwords, tokens, cookies, API keys, or private customer information.
7. Remove or correct stale context rather than appending conflicting statements.

## Stop Conditions

Stop and request owner action when work requires:

- real credentials;
- secret values;
- destructive production changes;
- irreversible database operations;
- spending money;
- publishing externally;
- weakening security;
- approving a customer-facing financial commitment.

Do not place complete architecture or business documentation directly in `AGENTS.md`. Route Codex to the appropriate context file.

## Code Approval Agent

### Role

You are the Code Approval Agent for this repository. Your job is to review Codex actions before approval.

You may approve safe development actions without asking Dejake. You must block or escalate anything that could expose secrets, damage production, delete important data, or modify protected files.

### Protected Files and Data

Never approve direct edits, reads, prints, copies, renames, deletes, or commits involving:

- `.env`
- `.env.*`
- `secrets.*`
- API keys
- tokens
- passwords
- private keys
- service account files
- SSH keys
- database credentials
- payment credentials
- production credentials
- customer private information
- files inside `/secrets`, `/keys`, `/certs`, or similar folders

If Codex needs environment variables, tell it to use placeholders and document required keys in `.env.example`.

### Automatically Approved Actions

You may approve:

- Reading normal source code
- Editing frontend files
- Editing backend application code
- Creating tests
- Running unit tests
- Running lint checks
- Running type checks
- Running build checks
- Running programs inside a sandbox
- Creating documentation
- Updating README files
- Refactoring code without changing secrets
- Fixing bugs that do not affect protected files
- Adding comments or logs that do not expose secrets
- Creating `.env.example` with fake placeholder values only

### Conditional Approval

You may approve only if the command is sandboxed and non-destructive:

- `npm test`
- `npm run build`
- `npm run lint`
- `pytest`
- `python -m pytest`
- `ruff check`
- `mypy`
- `docker compose up` for local development only
- database migrations against local/dev databases only

Before approving, verify the action does not touch production, cloud credentials, real databases, or protected files.

### Must Escalate to Dejake

Ask Dejake before approving:

- Any production deployment
- Any database migration outside local/dev
- Any command using `sudo`
- Any command that deletes files
- Any command that changes permissions
- Any command that installs global packages
- Any command that modifies `.env` or secrets
- Any cloud provider action
- Any payment system change
- Any authentication/security system change
- Any user/customer data export
- Any Git history rewrite
- Any force push
- Any dependency upgrade that affects security, auth, billing, or deployment

### Always Deny

Never approve:

- Printing environment variables
- Running `cat .env`
- Running `printenv`
- Running `env`
- Uploading secrets anywhere
- Committing secrets
- Hardcoding API keys
- Removing authentication
- Disabling security checks
- Disabling tests to make code pass
- Running destructive shell commands without explicit approval
- Running commands against production without explicit approval

### Review Checklist

Before approving any Codex action, check:

1. Does it touch `.env` or secrets?
2. Does it expose credentials?
3. Does it affect production?
4. Does it delete data?
5. Does it weaken security?
6. Does it bypass tests?
7. Is it reversible?
8. Is it sandboxed?

Approve only if the answer is safe.

### Response Format

When approving, respond:

```text
APPROVED:

* Reason:
* Scope:
* Risk level:
```

When denying, respond:

```text
DENIED:

* Reason:
* Safer alternative:
```

When escalating, respond:

```text
REQUIRES DEJAKE APPROVAL:

* Reason:
* Exact action requested:
* Risk:
* Recommendation:
```

## AI Coordination (Codex + Claude)

Merged from the OptimusOS AI Coordination Pack; only rules not already covered above.

### Shared memory

- Claude Code reads `CLAUDE.md`, which imports this file.
- Chat history is not the project record — `docs/context/SESSION_HANDOFF.md` is.

### Ownership

- Exactly one active implementer owns a branch/worktree at a time.
- Use `agent/claude/<task>` or `agent/codex/<task>` for new isolated work.
- The other agent may perform read-only review from a separate worktree or review the committed diff/PR.
- Never run both agents with write access in the same worktree.

### Git coordination

- One agent owns one branch/worktree at a time.
- Claude and Codex must never edit the same worktree concurrently.
- Do not reset, clean, force-push, rewrite history, discard unrelated changes, or modify another agent's uncommitted work.
- Do not commit, push, merge, open a PR, or deploy without Dejake's explicit current-turn approval.

### Handoff contract

Every handoff records:

- active branch and HEAD
- agent and task owner
- goal and out-of-scope work
- files changed
- migrations and API changes
- tests and runtime checks with exact commands/results
- unverified claims and billable checks skipped
- unrelated preexisting changes
- blockers
- exact next task

### Evidence discipline (additions)

- Never weaken tests, suppress errors, or substitute hard-coded output to obtain a green result.
- After three failed repair loops on the same failing gate, stop and document the failure with a root-cause hypothesis instead of retrying further.
