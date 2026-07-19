from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Generator
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, text

_PG_PORT = 15989
_PG_CONTAINER = "optimus_e2e_membership_boundary_pg"
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
    raise TimeoutError("Timed out waiting for membership-migration Postgres.")


@dataclass(frozen=True, slots=True)
class PreBoundaryDatabase:
    database_url: str
    env: dict[str, str]
    owner_id: int
    shop_id: int
    inactive_technician_id: int


@pytest.fixture
def pre_boundary_database() -> Generator[PreBoundaryDatabase, None, None]:
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
            ["uv", "run", "alembic", "upgrade", "021_part_allocations"], check=True, env=env
        )
        engine = create_engine(_DATABASE_URL)
        with engine.begin() as connection:
            owner_id = connection.execute(
                text(
                    "INSERT INTO user_accounts "
                    "(username, display_name, role, password_hash, is_active, is_synthetic_test_account) "
                    "VALUES ('owner', 'Owner', 'owner', 'fake-hash', true, false) RETURNING id"
                )
            ).scalar_one()
            inactive_technician_id = connection.execute(
                text(
                    "INSERT INTO user_accounts "
                    "(username, display_name, role, shop_owner_id, password_hash, is_active, "
                    "is_synthetic_test_account) "
                    "VALUES ('offboarded-tech', 'Offboarded Tech', 'technician', :owner_id, "
                    "'fake-hash', false, false) RETURNING id"
                ),
                {"owner_id": owner_id},
            ).scalar_one()
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "027_email_verification"], check=True, env=env
        )
        with engine.begin() as connection:
            shop_id = connection.execute(
                text(
                    "SELECT shop_id FROM shop_memberships "
                    "WHERE user_account_id = :owner_id AND role = 'owner'"
                ),
                {"owner_id": owner_id},
            ).scalar_one()
        engine.dispose()
        yield PreBoundaryDatabase(_DATABASE_URL, env, owner_id, shop_id, inactive_technician_id)
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)


def test_upgrade_backfills_real_technicians_and_round_trips(
    pre_boundary_database: PreBoundaryDatabase,
) -> None:
    engine = create_engine(pre_boundary_database.database_url)
    with engine.begin() as connection:
        real_technician_id = connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, shop_owner_id, password_hash, is_active, "
                "is_synthetic_test_account) "
                "VALUES ('late-tech', 'Late Tech', 'technician', :owner_id, 'fake-hash', true, false) "
                "RETURNING id"
            ),
            {"owner_id": pre_boundary_database.owner_id},
        ).scalar_one()
        inactive_technician_id = pre_boundary_database.inactive_technician_id
        synthetic_technician_id = connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, shop_owner_id, password_hash, is_active, "
                "is_synthetic_test_account) "
                "VALUES ('synthetic-tech', 'Synthetic Tech', 'technician', :owner_id, 'fake-hash', "
                "true, true) RETURNING id"
            ),
            {"owner_id": pre_boundary_database.owner_id},
        ).scalar_one()
        inconsistent_customer_id = connection.execute(
            text(
                "INSERT INTO customers (owner_user_id, shop_id, first_name, last_name) "
                "VALUES (:wrong_owner_id, :shop_id, 'Legacy', 'Mismatch') RETURNING id"
            ),
            {
                "wrong_owner_id": real_technician_id,
                "shop_id": pre_boundary_database.shop_id,
            },
        ).scalar_one()

    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], check=True, env=pre_boundary_database.env
    )
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT user_account_id, shop_id, role FROM shop_memberships "
                "WHERE user_account_id IN (:real_id, :inactive_id, :synthetic_id) "
                "ORDER BY user_account_id"
            ),
            {
                "real_id": real_technician_id,
                "inactive_id": inactive_technician_id,
                "synthetic_id": synthetic_technician_id,
            },
        ).fetchall()
        assert {(row.user_account_id, row.shop_id, row.role) for row in rows} == {
            (real_technician_id, pre_boundary_database.shop_id, "technician"),
            (inactive_technician_id, pre_boundary_database.shop_id, "technician"),
        }
        inactive_membership = connection.execute(
            text("SELECT is_active FROM shop_memberships WHERE user_account_id = :inactive_id"),
            {"inactive_id": inactive_technician_id},
        ).scalar_one()
        assert inactive_membership is False
        canonical_owner_id = connection.execute(
            text("SELECT owner_user_id FROM customers WHERE id = :customer_id"),
            {"customer_id": inconsistent_customer_id},
        ).scalar_one()
        canonical_shop_owner_id = connection.execute(
            text("SELECT shop_owner_id FROM user_accounts WHERE id = :technician_id"),
            {"technician_id": real_technician_id},
        ).scalar_one()
        synthetic_shop_owner_id = connection.execute(
            text("SELECT shop_owner_id FROM user_accounts WHERE id = :technician_id"),
            {"technician_id": synthetic_technician_id},
        ).scalar_one()
        assert canonical_owner_id == pre_boundary_database.owner_id
        assert canonical_shop_owner_id == pre_boundary_database.owner_id
        assert synthetic_shop_owner_id == pre_boundary_database.owner_id
        connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, shop_owner_id, password_hash, is_active, "
                "is_synthetic_test_account) "
                "VALUES ('manager', 'Manager', 'manager', :owner_id, 'fake-hash', true, false)"
            ),
            {"owner_id": pre_boundary_database.owner_id},
        )

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM user_accounts WHERE role = 'manager'"))
    subprocess.run(
        ["uv", "run", "alembic", "downgrade", "027_email_verification"],
        check=True,
        env=pre_boundary_database.env,
    )
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], check=True, env=pre_boundary_database.env
    )
    with engine.begin() as connection:
        inactive_after_round_trip = connection.execute(
            text("SELECT is_active FROM shop_memberships WHERE user_account_id = :inactive_id"),
            {"inactive_id": inactive_technician_id},
        ).scalar_one()
        assert inactive_after_round_trip is False
    engine.dispose()
