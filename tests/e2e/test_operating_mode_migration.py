from __future__ import annotations

import os
import subprocess
import time

from sqlalchemy import create_engine, text

_PG_PORT = 15993
_PG_CONTAINER = "optimus_e2e_operating_mode_pg"
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
    raise TimeoutError("Timed out waiting for operating-mode Postgres.")


def test_operating_mode_migration_round_trip_and_backfill() -> None:
    """ADR-022 capability foundation, slice 1: proves the real migration
    round-trips on real Postgres and backfills a pre-existing shop (the
    real pilot install's own scenario) to 'shop', mirroring
    test_subscription_billing_migration.py's identical shape for the
    closest prior precedent (another additive column + backfill + audit
    event on the same `shops`/`shop_events` tables)."""
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
            ["uv", "run", "alembic", "upgrade", "033_support_impersonation"],
            check=True,
            env=env,
        )
        engine = create_engine(_DATABASE_URL)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO shops (display_name, status) VALUES "
                    "('Pre-existing Operating-Mode Shop', 'active')"
                )
            )
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        with engine.begin() as connection:
            columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'shops'"
                    )
                )
            }
            assert "operating_mode" in columns
            constraints = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.table_constraints "
                        "WHERE table_name = 'shops'"
                    )
                )
            }
            assert "ck_shops_operating_mode" in constraints
            row = connection.execute(
                text(
                    "SELECT operating_mode FROM shops "
                    "WHERE display_name = 'Pre-existing Operating-Mode Shop'"
                )
            ).one()
            assert row.operating_mode == "shop"
            event_row = connection.execute(
                text(
                    "SELECT event_type, event_metadata FROM shop_events se "
                    "JOIN shops sh ON sh.id = se.shop_id "
                    "WHERE sh.display_name = 'Pre-existing Operating-Mode Shop' "
                    "AND se.event_type = 'operating_mode_backfilled'"
                )
            ).one()
            assert event_row.event_type == "operating_mode_backfilled"
            assert event_row.event_metadata == {"operating_mode": "shop"}
            # A brand-new shop inserted after the migration also gets the
            # safe default with no explicit value -- proves the
            # server_default, not just the one-time backfill UPDATE, is
            # what protects future inserts.
            connection.execute(
                text(
                    "INSERT INTO shops (display_name, status) VALUES "
                    "('Post-migration New Shop', 'active')"
                )
            )
            new_row = connection.execute(
                text(
                    "SELECT operating_mode FROM shops WHERE display_name = 'Post-migration New Shop'"
                )
            ).one()
            assert new_row.operating_mode == "shop"
        # NOT NULL is enforced. Run in its own connection/transaction scope
        # -- catching the expected failure inside the block above would
        # leave that transaction aborted for its own implicit commit on
        # `with` exit, since Postgres aborts a transaction on the first
        # failed statement within it.
        null_rejected = False
        try:
            with engine.begin() as null_connection:
                null_connection.execute(
                    text(
                        "INSERT INTO shops (display_name, status, operating_mode) "
                        "VALUES ('Null Mode Shop', 'active', NULL)"
                    )
                )
        except Exception:
            null_rejected = True
        assert null_rejected
        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "033_support_impersonation"],
            check=True,
            env=env,
        )
        with engine.begin() as connection:
            columns = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'shops'"
                    )
                )
            }
            assert "operating_mode" not in columns
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
