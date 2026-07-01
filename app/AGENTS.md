# Backend Guidance

## Scope

This file applies to backend work under `app/` and related migration or backend test changes.

## Read Before Backend Work

- `docs/context/CURRENT_STATE.md`
- `docs/context/SESSION_HANDOFF.md`
- `docs/context/SECURITY.md`

## Backend Rules

- Keep FastAPI route behavior aligned with the checked-in API contracts.
- Use `get_db_session` and SQLAlchemy sessions for database access.
- Put schema changes in Alembic migrations, not ad hoc SQL in application code.
- Keep authentication server-side with cookie-backed sessions.
- Preserve structured API errors and avoid leaking secrets in logs or responses.
- Treat `app/auth.py`, `app/db.py`, `app/db_models.py`, `app/main.py`, and `app/models.py` as the primary backend reference points.
- Add or update backend tests when changing auth, session handling, API validation, or migration behavior.
- Do not edit generated `dist/` artifacts.
