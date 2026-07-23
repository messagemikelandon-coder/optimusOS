from __future__ import annotations

import os
import subprocess
import time

from sqlalchemy import create_engine, text

_PG_PORT = 15993
_PG_CONTAINER = "optimus_e2e_job_compilation_pg"
_DATABASE_URL = f"postgresql+psycopg://optimus:optimus_local@127.0.0.1:{_PG_PORT}/optimus_os"

_NEW_TABLES = {"job_compilations", "job_compilation_events"}


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
    raise TimeoutError("Timed out waiting for job-compilation Postgres.")


def _tables(engine) -> set[str]:  # type: ignore[no-untyped-def]
    with engine.begin() as connection:
        return {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            )
        }


def test_job_compilation_migration_round_trip() -> None:
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
        # Upgrade to the revision just before the job-compiler slice: the two
        # new tables must not exist yet.
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "036_diagnostic_evidence"],
            check=True,
            env=env,
        )
        engine = create_engine(_DATABASE_URL)
        assert not (_NEW_TABLES & _tables(engine))

        # Upgrade to head applies 037: both tables appear.
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        assert _tables(engine) >= _NEW_TABLES
        with engine.begin() as connection:
            constraints = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.table_constraints "
                        "WHERE table_name = 'job_compilations'"
                    )
                )
            }
            assert "ck_job_compilations_status" in constraints

        # Downgrade removes the tables cleanly; re-upgrade restores head.
        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "036_diagnostic_evidence"],
            check=True,
            env=env,
        )
        assert not (_NEW_TABLES & _tables(engine))
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        assert _tables(engine) >= _NEW_TABLES
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
