from __future__ import annotations

import os
import subprocess
import time

from sqlalchemy import create_engine, text

_PG_PORT = 15992
_PG_CONTAINER = "optimus_e2e_subscription_billing_pg"
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
    raise TimeoutError("Timed out waiting for subscription-billing Postgres.")


def test_subscription_billing_migration_round_trip_and_backfill() -> None:
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
            ["uv", "run", "alembic", "upgrade", "030_workflow_gaps"], check=True, env=env
        )
        engine = create_engine(_DATABASE_URL)
        # A pre-existing shop (the real pilot install's own scenario) must
        # exist before this migration runs, so its backfill has a real row
        # to grandfather -- this is exactly why the migration walks every
        # row in `shops`, not just ones created after it.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO shops (display_name, status) VALUES "
                    "('Pre-existing Shop', 'active')"
                )
            )
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        with engine.begin() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                    )
                )
            }
            assert "shop_subscriptions" in tables
            constraints = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.table_constraints "
                        "WHERE table_name = 'shop_subscriptions'"
                    )
                )
            }
            assert {
                "uq_shop_subscriptions_shop_id",
                "ck_shop_subscriptions_tier",
                "ck_shop_subscriptions_billing_status",
            } <= constraints
            row = connection.execute(
                text(
                    "SELECT tier, billing_status, seat_limit, trial_ends_at FROM "
                    "shop_subscriptions s JOIN shops sh ON sh.id = s.shop_id "
                    "WHERE sh.display_name = 'Pre-existing Shop'"
                )
            ).one()
            assert row.tier == "shop"
            assert row.billing_status == "active"
            assert row.seat_limit is None
            assert row.trial_ends_at is None
            event_row = connection.execute(
                text(
                    "SELECT event_type FROM shop_events se JOIN shops sh ON sh.id = se.shop_id "
                    "WHERE sh.display_name = 'Pre-existing Shop' "
                    "AND se.event_type = 'subscription_grandfathered'"
                )
            ).one()
            assert event_row.event_type == "subscription_grandfathered"
        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "030_workflow_gaps"], check=True, env=env
        )
        with engine.begin() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                    )
                )
            }
            assert "shop_subscriptions" not in tables
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
