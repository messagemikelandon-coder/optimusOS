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
