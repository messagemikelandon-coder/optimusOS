from __future__ import annotations

import os
import subprocess
import time

from sqlalchemy import create_engine, text

_PG_PORT = 15992
_PG_CONTAINER = "optimus_e2e_diag_evidence_pg"
_DATABASE_URL = f"postgresql+psycopg://optimus:optimus_local@127.0.0.1:{_PG_PORT}/optimus_os"

_NEW_COLUMNS = {"complaint", "confidence", "severity", "recommended_next_test"}
_NEW_CONSTRAINTS = {"ck_diagnostic_findings_confidence", "ck_diagnostic_findings_severity"}


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
    raise TimeoutError("Timed out waiting for diagnostic-evidence Postgres.")


def _diagnostic_columns(engine) -> set[str]:  # type: ignore[no-untyped-def]
    with engine.begin() as connection:
        return {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'diagnostic_findings'"
                )
            )
        }


def test_diagnostic_evidence_migration_round_trip() -> None:
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
        # Upgrade to the revision just before the evidence slice: the new columns
        # must not exist yet.
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "035_operating_mode_confirmed_at"],
            check=True,
            env=env,
        )
        engine = create_engine(_DATABASE_URL)
        assert not (_NEW_COLUMNS & _diagnostic_columns(engine))

        # Upgrade to head applies 036: columns and CHECK constraints appear.
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        assert _diagnostic_columns(engine) >= _NEW_COLUMNS
        with engine.begin() as connection:
            constraints = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.table_constraints "
                        "WHERE table_name = 'diagnostic_findings'"
                    )
                )
            }
            assert constraints >= _NEW_CONSTRAINTS

        # Downgrade removes the columns cleanly; re-upgrade restores head.
        subprocess.run(
            ["uv", "run", "alembic", "downgrade", "035_operating_mode_confirmed_at"],
            check=True,
            env=env,
        )
        assert not (_NEW_COLUMNS & _diagnostic_columns(engine))
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)
        assert _diagnostic_columns(engine) >= _NEW_COLUMNS
        engine.dispose()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)
