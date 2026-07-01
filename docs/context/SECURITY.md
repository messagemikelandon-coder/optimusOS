# Security

Purpose: secret-handling, auth, and trust-boundary rules for the repository.
Information owner: repository maintainers and the owner responsible for credentials.
Read when: changing auth, API access, deployment, logging, secrets, or database migration behavior.
Update when: security boundaries, credentials flow, or verification commands change.
Last verified date: 2026-07-01.
Relevant sources: `app/config.py`, `app/auth.py`, `app/security.py`, `app/main.py`, `alembic/versions/002_authentication_tables.py`, `docker-compose.yml`, `scripts/check_config.py`, `scripts/validate_runtime.py`, `tests/test_auth.py`, `tests/test_security.py`, `docs/frontend-audit.md`.

## Rules

- Keep secrets in `.env` and out of Git history.
- Do not print or copy secret values into documentation.
- The browser must never receive OpenAI or other server API keys.
- Authentication uses server-side sessions and an HttpOnly cookie.
- Passwords are hashed with Argon2 before storage.
- Session tokens are hashed with SHA-256 before storage.
- Cookie transport must remain HttpOnly and same-site protected.
- Authorization checks must remain server-side and should not be bypassed in client code.
- Logs must not leak raw passwords, session tokens, API keys, or customer secrets.
- CORS should remain limited to the local frontend origins used by the Compose/Nginx setup.
- Owner bootstrap should only create the first owner when credentials are provided through the environment.
- Database migrations must be applied through Alembic before auth-dependent startup assumptions are made.
- Prohibited development bypasses include hardcoded credentials, plaintext token storage, and disabling auth to make tests pass.

## Verified Implementation Details

- `.env` is ignored by Git.
- `Settings` reads `.env` and strips the sensitive values before use.
- Auth sessions are stored in PostgreSQL in `user_accounts` and `auth_sessions`.
- The session cookie name is `optimus_session`.
- The cookie is marked `HttpOnly` and `SameSite=Lax`; `Secure` is enabled when the frontend origin is HTTPS.
- `ops/nginx/default.conf` keeps the browser on the local origin and proxies `/api/`, `/health`, and `/ready` to FastAPI.
- The frontend uses relative `/api/...` paths and `credentials: "same-origin"`.

## Security Verification Commands

```bash
git check-ignore -v .env
python scripts/check_config.py
python scripts/validate_runtime.py
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_auth.py tests/test_security.py tests/test_api.py -vv
```

## Incident Response For Leaked Credentials

1. Remove the leaked value from `.env`, Git history, or logs.
2. Rotate the affected secret immediately.
3. Revoke or expire any sessions that could have been issued with the leaked credential.
4. Re-run auth and security checks before resuming work.
5. Update `KNOWN_ISSUES.md` if the leak created a repo-tracked defect.
