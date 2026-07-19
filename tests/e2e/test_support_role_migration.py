from __future__ import annotations

import os
import subprocess
import time

from sqlalchemy import create_engine, text

_PG_PORT = 15993
_PG_CONTAINER = "optimus_e2e_support_role_pg"
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
    raise TimeoutError("Timed out waiting for support-role Postgres.")


def test_support_role_migration_round_trip_and_rejects_downgrade_with_a_support_row() -> None:
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
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "031_subscription_billing"], check=True, env=env
        )
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        engine = create_engine(_DATABASE_URL)
        with engine.begin() as connection:
            constraint = connection.execute(
                text(
                    "SELECT check_clause FROM information_schema.check_constraints "
                    "WHERE constraint_name = 'ck_user_accounts_role'"
                )
            ).scalar()
            assert constraint is not None and "support" in constraint
            # A real INSERT proves the widened constraint actually accepts
            # the new role, not just that the constraint text mentions it.
            connection.execute(
                text(
                    "INSERT INTO user_accounts (username, display_name, role, "
                    "password_hash, is_active, account_status) VALUES "
                    "('support-migration-test', 'Support', 'support', 'x', true, 'active')"
                )
            )

        # A separate transaction: Postgres aborts the whole transaction after
        # any statement error, which would otherwise also roll back the
        # legitimate insert just committed above.
        rejected = False
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO user_accounts (username, display_name, role, "
                        "password_hash, is_active, account_status) VALUES "
                        "('bad-role-test', 'Bad', 'nonsense-role', 'x', true, 'active')"
                    )
                )
        except Exception:
            rejected = True
        assert rejected, "the CHECK constraint should still reject an unknown role"

        # Downgrading while a real support row exists must fail loudly, not
        # silently orphan/corrupt that row or drop it.
        downgrade_result = subprocess.run(
            ["uv", "run", "alembic", "downgrade", "031_subscription_billing"],
            capture_output=True,
            env=env,
        )
        assert downgrade_result.returncode != 0
        assert b"Cannot downgrade support role" in downgrade_result.stderr

        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM user_accounts WHERE username = 'support-migration-test'")
            )
        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "031_subscription_billing"], check=True, env=env
        )
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
