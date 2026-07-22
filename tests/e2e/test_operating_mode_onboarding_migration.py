from __future__ import annotations

import os
import subprocess
import time

from sqlalchemy import create_engine, text

_PG_PORT = 15994
_PG_CONTAINER = "optimus_e2e_onboarding_pg"
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
    raise TimeoutError("Timed out waiting for onboarding Postgres.")


def test_onboarding_confirmation_migration_backfill_and_round_trip() -> None:
    """ADR-022 post-signup onboarding: proves migration 035 on real Postgres
    backfills every pre-existing shop's `operating_mode_confirmed_at` to the
    migration timestamp (so established shops are treated as already-confirmed
    and never see the first-run card), leaves shops created afterwards NULL
    (unconfirmed), and downgrades/upgrades cleanly. Mirrors
    test_operating_mode_migration.py's shape for the closest precedent."""
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
        # Upgrade to the revision immediately before 035, then plant a
        # pre-existing shop the way an established install would have one.
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "034_operating_mode"], check=True, env=env
        )
        engine = create_engine(_DATABASE_URL)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO shops (display_name, status) VALUES "
                    "('Pre-existing Onboarding Shop', 'active')"
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
            assert "operating_mode_confirmed_at" in columns

            # Pre-existing shop backfilled to a real timestamp (not NULL).
            row = connection.execute(
                text(
                    "SELECT operating_mode_confirmed_at FROM shops "
                    "WHERE display_name = 'Pre-existing Onboarding Shop'"
                )
            ).one()
            assert row.operating_mode_confirmed_at is not None

            # And a backfill audit event was written.
            event_row = connection.execute(
                text(
                    "SELECT event_type FROM shop_events se "
                    "JOIN shops sh ON sh.id = se.shop_id "
                    "WHERE sh.display_name = 'Pre-existing Onboarding Shop' "
                    "AND se.event_type = 'operating_mode_confirmation_backfilled'"
                )
            ).one()
            assert event_row.event_type == "operating_mode_confirmation_backfilled"

            # A shop created *after* the migration stays unconfirmed (NULL),
            # since there is deliberately no server default -- so its owner
            # gets the first-run card.
            connection.execute(
                text(
                    "INSERT INTO shops (display_name, status) VALUES "
                    "('Post-035 New Shop', 'active')"
                )
            )
            new_row = connection.execute(
                text(
                    "SELECT operating_mode_confirmed_at FROM shops "
                    "WHERE display_name = 'Post-035 New Shop'"
                )
            ).one()
            assert new_row.operating_mode_confirmed_at is None

        # Clean downgrade drops the column; upgrade restores it.
        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "034_operating_mode"], check=True, env=env
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
            assert "operating_mode_confirmed_at" not in columns
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
