from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Generator
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, text

_PG_PORT = 15993
_PG_CONTAINER = "optimus_e2e_shop_id_not_null_pg"
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
def pre_025_database() -> Generator[MigratedDatabase, None, None]:
    """A real, isolated Postgres 16 container migrated up to (but not past)
    024_backfill_shop_id -- so rows (including deliberately orphaned ones)
    can be seeded before migration 025's NOT NULL constraint runs.
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
            ["uv", "run", "alembic", "upgrade", "024_backfill_shop_id"], check=True, env=env
        )
        yield MigratedDatabase(database_url=_DATABASE_URL, env=env)
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)


def test_not_null_migration_succeeds_when_no_orphans_exist(
    pre_025_database: MigratedDatabase,
) -> None:
    engine = create_engine(pre_025_database.database_url)
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
                "INSERT INTO customers (owner_user_id, shop_id, first_name, last_name) "
                "VALUES (:owner_id, :shop_id, 'Jane', 'Doe')"
            ),
            {"owner_id": owner_id, "shop_id": shop_id},
        )

    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], check=True, env=pre_025_database.env
    )

    with engine.begin() as connection:
        is_nullable = connection.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'customers' AND column_name = 'shop_id'"
            )
        ).scalar_one()
    engine.dispose()
    assert is_nullable == "NO"


def test_not_null_migration_refuses_to_proceed_with_orphan_rows(
    pre_025_database: MigratedDatabase,
) -> None:
    engine = create_engine(pre_025_database.database_url)
    with engine.begin() as connection:
        owner_id = connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, password_hash, is_active, is_synthetic_test_account) "
                "VALUES ('owner', 'Owner', 'owner', 'fake-hash', true, false) RETURNING id"
            )
        ).scalar_one()
        # No shop/membership for this owner -- customers.shop_id stays NULL.
        connection.execute(
            text(
                "INSERT INTO customers (owner_user_id, shop_id, first_name, last_name) "
                "VALUES (:owner_id, NULL, 'Orphan', 'Row')"
            ),
            {"owner_id": owner_id},
        )

    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=pre_025_database.env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Refusing to add NOT NULL constraints" in result.stderr
    assert "customers=1" in result.stderr

    with engine.begin() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        is_nullable = connection.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'customers' AND column_name = 'shop_id'"
            )
        ).scalar_one()
    engine.dispose()
    assert version == "024_backfill_shop_id"
    assert is_nullable == "YES"
