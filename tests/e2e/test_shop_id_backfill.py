from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Generator
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, text

_PG_PORT = 15991
_PG_CONTAINER = "optimus_e2e_shop_id_backfill_pg"
_DATABASE_URL = f"postgresql+psycopg://optimus:optimus_local@127.0.0.1:{_PG_PORT}/optimus_os"


def _wait_for(predicate, timeout_seconds: float, description: str) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # retry until timeout
            last_error = exc
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for {description}") from last_error


@dataclass(frozen=True, slots=True)
class MigratedDatabase:
    database_url: str
    env: dict[str, str]


@pytest.fixture
def pre_024_database() -> Generator[MigratedDatabase, None, None]:
    """A real, isolated Postgres 16 container migrated up to (but not past)
    023_shop_id_nullable_columns -- so business-table rows can be seeded
    with a real `owner_user_id` and a NULL `shop_id` before migration
    024's backfill runs, mirroring
    tests/e2e/test_shop_tenant_migration_backfill.py's approach for
    migration 022 (a distinct container/port from that file's fixture and
    from tests/e2e/conftest.py's shared `live_server` fixture, since none
    of those can seed rows at this specific point in the migration chain).
    """
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
        _wait_for(
            lambda: (
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        _PG_CONTAINER,
                        "pg_isready",
                        "-U",
                        "optimus",
                        "-d",
                        "optimus_os",
                    ],
                    capture_output=True,
                    check=False,
                ).returncode
                == 0
            ),
            timeout_seconds=30,
            description="Postgres to become ready",
        )
        env = {
            **os.environ,
            "DATABASE_URL": _DATABASE_URL,
            "APP_ENV": "test",
            "OPENAI_API_KEY": "e2e-test-placeholder",
        }
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "023_shop_id_nullable_columns"], check=True, env=env
        )
        yield MigratedDatabase(database_url=_DATABASE_URL, env=env)
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)


def _run_migration_to_head(env: dict[str, str]) -> None:
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)


def test_backfill_sets_shop_id_from_owner_membership_and_leaves_orphans_null(
    pre_024_database: MigratedDatabase,
) -> None:
    engine = create_engine(pre_024_database.database_url)
    with engine.begin() as connection:
        owner_id = connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, password_hash, is_active, is_synthetic_test_account) "
                "VALUES ('owner', 'Owner', 'owner', 'fake-hash', true, false) RETURNING id"
            )
        ).scalar_one()
        technician_id = connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, shop_owner_id, password_hash, is_active, "
                "is_synthetic_test_account) "
                "VALUES ('tech.one', 'Tech One', 'technician', :owner_id, 'fake-hash', true, false) "
                "RETURNING id"
            ),
            {"owner_id": owner_id},
        ).scalar_one()

        shop_id = connection.execute(
            text(
                "INSERT INTO shops (display_name, status) VALUES ('Landon Motor Works', 'active') RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO shop_memberships (shop_id, user_account_id, role) "
                "VALUES (:shop_id, :owner_id, 'owner')"
            ),
            {"shop_id": shop_id, "owner_id": owner_id},
        )

        real_customer_id = connection.execute(
            text(
                "INSERT INTO customers (owner_user_id, first_name, last_name) "
                "VALUES (:owner_id, 'Jane', 'Doe') RETURNING id"
            ),
            {"owner_id": owner_id},
        ).scalar_one()
        # Orphan case: owner_user_id references a real user_account, but one
        # with no *owner*-role ShopMembership -- must be left NULL, not
        # mis-attached to the shop via some other membership row.
        orphan_customer_id = connection.execute(
            text(
                "INSERT INTO customers (owner_user_id, first_name, last_name) "
                "VALUES (:technician_id, 'Orphan', 'Row') RETURNING id"
            ),
            {"technician_id": technician_id},
        ).scalar_one()

    _run_migration_to_head(pre_024_database.env)

    with engine.begin() as connection:
        rows = connection.execute(text("SELECT id, shop_id FROM customers ORDER BY id")).fetchall()
        shop_id_by_customer = {row.id: row.shop_id for row in rows}
        assert shop_id_by_customer[real_customer_id] == shop_id
        assert shop_id_by_customer[orphan_customer_id] is None
    engine.dispose()


def test_backfill_is_idempotent_across_repeated_runs(pre_024_database: MigratedDatabase) -> None:
    engine = create_engine(pre_024_database.database_url)
    with engine.begin() as connection:
        owner_id = connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, password_hash, is_active, is_synthetic_test_account) "
                "VALUES ('owner', 'Owner', 'owner', 'fake-hash', true, false) RETURNING id"
            )
        ).scalar_one()
        shop_id = connection.execute(
            text(
                "INSERT INTO shops (display_name, status) VALUES ('Landon Motor Works', 'active') RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO shop_memberships (shop_id, user_account_id, role) "
                "VALUES (:shop_id, :owner_id, 'owner')"
            ),
            {"shop_id": shop_id, "owner_id": owner_id},
        )
        connection.execute(
            text(
                "INSERT INTO customers (owner_user_id, first_name, last_name) VALUES (:owner_id, 'Jane', 'Doe')"
            ),
            {"owner_id": owner_id},
        )

    _run_migration_to_head(pre_024_database.env)
    # Re-running the same migration's upgrade (via a no-op downgrade+upgrade
    # round trip) must not error or double-assign -- WHERE shop_id IS NULL
    # means the second pass finds nothing left to do.
    subprocess.run(
        ["uv", "run", "alembic", "downgrade", "023_shop_id_nullable_columns"],
        check=True,
        env=pre_024_database.env,
    )
    _run_migration_to_head(pre_024_database.env)

    with engine.begin() as connection:
        result = connection.execute(text("SELECT shop_id FROM customers")).scalar_one()
    engine.dispose()
    assert result == shop_id


def test_downgrade_clears_shop_id_but_keeps_the_column(pre_024_database: MigratedDatabase) -> None:
    engine = create_engine(pre_024_database.database_url)
    with engine.begin() as connection:
        owner_id = connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, password_hash, is_active, is_synthetic_test_account) "
                "VALUES ('owner', 'Owner', 'owner', 'fake-hash', true, false) RETURNING id"
            )
        ).scalar_one()
        shop_id = connection.execute(
            text(
                "INSERT INTO shops (display_name, status) VALUES ('Landon Motor Works', 'active') RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO shop_memberships (shop_id, user_account_id, role) "
                "VALUES (:shop_id, :owner_id, 'owner')"
            ),
            {"shop_id": shop_id, "owner_id": owner_id},
        )
        connection.execute(
            text(
                "INSERT INTO customers (owner_user_id, first_name, last_name) VALUES (:owner_id, 'Jane', 'Doe')"
            ),
            {"owner_id": owner_id},
        )

    _run_migration_to_head(pre_024_database.env)
    subprocess.run(
        ["uv", "run", "alembic", "downgrade", "023_shop_id_nullable_columns"],
        check=True,
        env=pre_024_database.env,
    )

    with engine.begin() as connection:
        shop_id_value = connection.execute(text("SELECT shop_id FROM customers")).scalar_one()
        column_exists = connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'customers' AND column_name = 'shop_id'"
            )
        ).scalar_one_or_none()
    engine.dispose()
    assert shop_id_value is None
    assert column_exists == "shop_id"
