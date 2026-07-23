from __future__ import annotations

import os
import subprocess
import time

from sqlalchemy import create_engine, text

_PG_PORT = 15995
_PG_CONTAINER = "optimus_e2e_job_release_pg"
_DATABASE_URL = f"postgresql+psycopg://optimus:optimus_local@127.0.0.1:{_PG_PORT}/optimus_os"

_NEW_COLUMNS = {"released_estimate_id", "released_at", "released_by_user_id"}


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
    raise TimeoutError("Timed out waiting for job-release Postgres.")


def _columns(engine) -> set[str]:  # type: ignore[no-untyped-def]
    with engine.begin() as connection:
        return {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'job_compilations'"
                )
            )
        }


def test_job_compilation_release_migration_round_trip() -> None:
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
        # Just before this slice: the release columns must not exist yet.
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "038_intake_vehicle_draft"], check=True, env=env
        )
        engine = create_engine(_DATABASE_URL)
        assert not (_NEW_COLUMNS & _columns(engine))

        # Upgrade to head applies 039: the three release columns appear and the
        # event-type CHECK now allows 'released'.
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        assert _columns(engine) >= _NEW_COLUMNS
        with engine.begin() as connection:
            check_clause = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_job_compilation_events_type'"
                )
            ).scalar_one()
            assert "released" in check_clause

        # Downgrade removes the columns and restores the old CHECK; re-upgrade restores.
        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "038_intake_vehicle_draft"], check=True, env=env
        )
        assert not (_NEW_COLUMNS & _columns(engine))
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        assert _columns(engine) >= _NEW_COLUMNS
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
