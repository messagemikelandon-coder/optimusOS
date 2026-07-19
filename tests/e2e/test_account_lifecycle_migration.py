from __future__ import annotations

import os
import subprocess
import time

from sqlalchemy import create_engine, text

_PG_PORT = 15990
_PG_CONTAINER = "optimus_e2e_account_lifecycle_pg"
_DATABASE_URL = f"postgresql+psycopg://optimus:optimus_local@127.0.0.1:{_PG_PORT}/optimus_os"


def _wait_for_postgres() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        ready = subprocess.run(
            ["docker", "exec", _PG_CONTAINER, "pg_isready", "-U", "optimus", "-d", "optimus_os"],
            capture_output=True,
            check=False,
        )
        if ready.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError("Timed out waiting for account-lifecycle Postgres.")


def test_account_lifecycle_migration_backfills_and_round_trips() -> None:
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
            ["uv", "run", "alembic", "upgrade", "028_membership_tenant_boundary"],
            check=True,
            env=env,
        )
        engine = create_engine(_DATABASE_URL)
        with engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO user_accounts "
                    "(username, display_name, role, password_hash, is_active, "
                    "is_synthetic_test_account) "
                    "VALUES ('migration-owner', 'Migration Owner', 'owner', 'fake-hash', "
                    "true, false) RETURNING id"
                )
            ).scalar_one()
            shop_id = connection.execute(
                text(
                    "INSERT INTO shops (display_name, status) "
                    "VALUES ('Migration Shop', 'active') RETURNING id"
                )
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shop_memberships (shop_id, user_account_id, role) "
                    "VALUES (:shop_id, :owner_id, 'owner')"
                ),
                {"shop_id": shop_id, "owner_id": owner_id},
            )
            disabled_manager_id = connection.execute(
                text(
                    "INSERT INTO user_accounts "
                    "(username, display_name, role, shop_owner_id, password_hash, is_active, "
                    "is_synthetic_test_account) "
                    "VALUES ('disabled-manager', 'Disabled Manager', 'manager', :owner_id, "
                    "'fake-hash', false, false) RETURNING id"
                ),
                {"owner_id": owner_id},
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO shop_memberships "
                    "(shop_id, user_account_id, role, is_active) "
                    "VALUES (:shop_id, :manager_id, 'manager', false)"
                ),
                {"shop_id": shop_id, "manager_id": disabled_manager_id},
            )
            invitation_id = connection.execute(
                text(
                    "INSERT INTO shop_invitations "
                    "(shop_id, email, role, invited_by_user_account_id, token_hash, expires_at) "
                    "VALUES (:shop_id, ' Mixed.Case@Example.COM ', 'manager', :owner_id, "
                    ":token_hash, now() + interval '1 day') RETURNING id"
                ),
                {"shop_id": shop_id, "owner_id": owner_id, "token_hash": "a" * 64},
            ).scalar_one()
            duplicate_invitation_id = connection.execute(
                text(
                    "INSERT INTO shop_invitations "
                    "(shop_id, email, role, invited_by_user_account_id, token_hash, expires_at) "
                    "VALUES (:shop_id, 'mixed.case@example.com', 'technician', :owner_id, "
                    ":token_hash, now() + interval '1 day') RETURNING id"
                ),
                {"shop_id": shop_id, "owner_id": owner_id, "token_hash": "b" * 64},
            ).scalar_one()

        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        with engine.begin() as connection:
            account = connection.execute(
                text(
                    "SELECT account_status, failed_login_attempts FROM user_accounts "
                    "WHERE id = :owner_id"
                ),
                {"owner_id": owner_id},
            ).one()
            normalized = connection.execute(
                text("SELECT email_normalized FROM shop_invitations WHERE id = :invitation_id"),
                {"invitation_id": invitation_id},
            ).scalar_one()
            duplicate_state = connection.execute(
                text(
                    "SELECT email_normalized, revoked_at FROM shop_invitations "
                    "WHERE id = :invitation_id"
                ),
                {"invitation_id": duplicate_invitation_id},
            ).one()
            disabled_status = connection.execute(
                text("SELECT account_status FROM user_accounts WHERE id = :manager_id"),
                {"manager_id": disabled_manager_id},
            ).scalar_one()
            tables = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            }
            assert account.account_status == "active"
            assert account.failed_login_attempts == 0
            assert normalized == "mixed.case@example.com"
            assert duplicate_state.email_normalized == "mixed.case@example.com"
            assert duplicate_state.revoked_at is not None
            assert disabled_status == "disabled"
            assert {
                "password_reset_tokens",
                "auth_login_events",
                "auth_mfa_factors",
            } <= tables

        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "028_membership_tenant_boundary"],
            check=True,
            env=env,
        )
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
