from __future__ import annotations

import os
import subprocess
import time

from sqlalchemy import create_engine, text

_PG_PORT = 15991
_PG_CONTAINER = "optimus_e2e_workflow_gap_pg"
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
    raise TimeoutError("Timed out waiting for workflow-gap Postgres.")


def test_workflow_gap_migration_round_trip() -> None:
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
            ["uv", "run", "alembic", "upgrade", "029_account_lifecycle"], check=True, env=env
        )
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        engine = create_engine(_DATABASE_URL)
        with engine.begin() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                    )
                )
            }
            assert {"workflow_gaps", "workflow_gap_events"} <= tables
            constraints = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.table_constraints WHERE table_name IN ('workflow_gaps', 'workflow_gap_events')"
                    )
                )
            }
            assert {
                "ck_workflow_gaps_severity",
                "ck_workflow_gaps_status",
                "ck_workflow_gap_events_type",
            } <= constraints
        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "029_account_lifecycle"], check=True, env=env
        )
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
