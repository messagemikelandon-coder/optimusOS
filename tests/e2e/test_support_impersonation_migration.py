from __future__ import annotations

import os
import subprocess
import time

from sqlalchemy import create_engine, text

_PG_PORT = 15994
_PG_CONTAINER = "optimus_e2e_support_impersonation_pg"
_DATABASE_URL = f"postgresql+psycopg://optimus:optimus_local@127.0.0.1:{_PG_PORT}/optimus_os"


def _wait_for_postgres() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", _PG_CONTAINER, "pg_isready", "-U", "optimus", "-d", "optimus_os"],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError("Timed out waiting for support-impersonation Postgres.")


def test_support_impersonation_migration_round_trip() -> None:
    subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            _PG_CONTAINER,
            "-e",
            "POSTGRES_DB=optimus_os",
            "-e",
            "POSTGRES_USER=optimus",
            "-e",
            "POSTGRES_PASSWORD=optimus_local",
            "-p",
            f"{_PG_PORT}:5432",
            "postgres:16-alpine",
        ],
        check=True,
        capture_output=True,
    )
    try:
        _wait_for_postgres()
        env = {
            **os.environ,
            "DATABASE_URL": _DATABASE_URL,
            "APP_ENV": "test",
            "OPENAI_API_KEY": "e2e-test-placeholder",
        }
        subprocess.run(["uv", "run", "alembic", "upgrade", "032_support_role"], check=True, env=env)
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        engine = create_engine(_DATABASE_URL)
        with engine.begin() as connection:
            columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'auth_sessions'"
                    )
                )
            }
            assert "impersonated_by_user_account_id" in columns

            # A real end-to-end row proves the FK and SET NULL behavior, not
            # just that the column exists.
            owner_id = connection.execute(
                text(
                    "INSERT INTO user_accounts (username, display_name, role, "
                    "password_hash, is_active, account_status) VALUES "
                    "('impersonation-migration-owner', 'Owner', 'owner', 'x', true, "
                    "'active') RETURNING id"
                )
            ).scalar()
            support_id = connection.execute(
                text(
                    "INSERT INTO user_accounts (username, display_name, role, "
                    "password_hash, is_active, account_status) VALUES "
                    "('impersonation-migration-support', 'Support', 'support', 'x', "
                    "true, 'active') RETURNING id"
                )
            ).scalar()
            session_id = connection.execute(
                text(
                    "INSERT INTO auth_sessions (user_id, token_hash, expires_at, "
                    "impersonated_by_user_account_id) VALUES "
                    "(:owner_id, 'migration-test-hash', now() + interval '1 hour', "
                    ":support_id) RETURNING id"
                ),
                {"owner_id": owner_id, "support_id": support_id},
            ).scalar()
            connection.execute(
                text("DELETE FROM user_accounts WHERE id = :support_id"),
                {"support_id": support_id},
            )
            remaining = connection.execute(
                text("SELECT impersonated_by_user_account_id FROM auth_sessions WHERE id = :id"),
                {"id": session_id},
            ).scalar()
            assert remaining is None, (
                "deleting the support account must SET NULL, not cascade-delete the "
                "impersonated owner's session"
            )
        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "032_support_role"], check=True, env=env
        )
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
