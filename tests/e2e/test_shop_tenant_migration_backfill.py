from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Generator
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, text

_PG_PORT = 15988
_PG_CONTAINER = "optimus_e2e_shop_migration_pg"
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
def pre_022_database() -> Generator[MigratedDatabase, None, None]:
    """A real, isolated Postgres 16 container migrated up to (but not past)
    021_part_allocations -- a distinct container/port from
    tests/e2e/conftest.py's shared `live_server` fixture, since this test
    needs to seed rows *before* migration 022 runs, which that
    session-scoped, already-fully-migrated fixture cannot do.

    This closes a real gap an independent review found in Phase 3 slice 1
    (`docs/context/GOAL_EVIDENCE_MATRIX.md`): migration 022's own
    real-data backfill logic (`alembic/versions/022_shop_tenant_model.py`)
    had only ever been verified by a one-time manual rehearsal whose
    scratch container was deleted afterward -- CI's own migration checks
    only ever run against a database with zero existing rows, so the
    backfill loop body was never actually executed by any repeatable,
    committed check before this test.
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
            ["uv", "run", "alembic", "upgrade", "021_part_allocations"], check=True, env=env
        )
        yield MigratedDatabase(database_url=_DATABASE_URL, env=env)
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)


def _run_migration_to_head(env: dict[str, str]) -> None:
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)


def test_backfill_creates_one_shop_per_real_owner_and_excludes_synthetic_accounts(
    pre_022_database: MigratedDatabase,
) -> None:
    engine = create_engine(pre_022_database.database_url)
    with engine.begin() as connection:
        owner_id = connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, password_hash, is_active, is_synthetic_test_account) "
                "VALUES ('owner', 'Owner', 'owner', 'fake-hash', true, false) RETURNING id"
            )
        ).scalar_one()
        real_technician_id = connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, shop_owner_id, password_hash, is_active, "
                "is_synthetic_test_account) "
                "VALUES ('tech.real', 'Real Tech', 'technician', :owner_id, 'fake-hash', true, false) "
                "RETURNING id"
            ),
            {"owner_id": owner_id},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, shop_owner_id, password_hash, is_active, "
                "is_synthetic_test_account) "
                "VALUES ('tech.synthetic', 'Synthetic Tech', 'technician', :owner_id, 'fake-hash', "
                "true, true)"
            ),
            {"owner_id": owner_id},
        )

    _run_migration_to_head(pre_022_database.env)

    with engine.begin() as connection:
        shops = connection.execute(text("SELECT id, display_name, status FROM shops")).fetchall()
        assert len(shops) == 1
        assert shops[0].display_name == "Landon Motor Works"
        assert shops[0].status == "active"
        shop_id = shops[0].id

        settings_row = connection.execute(
            text("SELECT labor_rate FROM shop_settings WHERE shop_id = :shop_id"),
            {"shop_id": shop_id},
        ).one()
        assert settings_row.labor_rate is not None

        memberships = connection.execute(
            text(
                "SELECT user_account_id, role FROM shop_memberships "
                "WHERE shop_id = :shop_id ORDER BY user_account_id"
            ),
            {"shop_id": shop_id},
        ).fetchall()
        membership_by_user = {row.user_account_id: row.role for row in memberships}
        assert membership_by_user == {owner_id: "owner", real_technician_id: "technician"}

        events = connection.execute(
            text("SELECT event_type FROM shop_events WHERE shop_id = :shop_id"),
            {"shop_id": shop_id},
        ).fetchall()
        assert [row.event_type for row in events] == ["shop_backfilled_from_existing_owner"]
    engine.dispose()


def test_backfill_is_a_noop_when_no_owner_accounts_exist_yet(
    pre_022_database: MigratedDatabase,
) -> None:
    _run_migration_to_head(pre_022_database.env)

    engine = create_engine(pre_022_database.database_url)
    with engine.begin() as connection:
        shop_count = connection.execute(text("SELECT count(*) FROM shops")).scalar_one()
    engine.dispose()
    assert shop_count == 0


def test_downgrade_drops_shop_tables_without_touching_user_accounts(
    pre_022_database: MigratedDatabase,
) -> None:
    engine = create_engine(pre_022_database.database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO user_accounts "
                "(username, display_name, role, password_hash, is_active, is_synthetic_test_account) "
                "VALUES ('owner', 'Owner', 'owner', 'fake-hash', true, false)"
            )
        )

    _run_migration_to_head(pre_022_database.env)
    subprocess.run(
        ["uv", "run", "alembic", "downgrade", "021_part_allocations"],
        check=True,
        env=pre_022_database.env,
    )

    with engine.begin() as connection:
        remaining_shop_tables = connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name IN "
                "('shops', 'shop_settings', 'shop_memberships', 'shop_invitations', 'shop_events')"
            )
        ).fetchall()
        assert remaining_shop_tables == []

        owners = connection.execute(text("SELECT username FROM user_accounts")).fetchall()
        assert [row.username for row in owners] == ["owner"]
    engine.dispose()
