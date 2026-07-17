from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Generator
from dataclasses import dataclass

import httpx
import pytest

_PG_PORT = 15987
_PG_CONTAINER = "optimus_e2e_pg"
_APP_PORT = 18099
_DATABASE_URL = f"postgresql+psycopg://optimus:optimus_local@127.0.0.1:{_PG_PORT}/optimus_os"


@dataclass(frozen=True, slots=True)
class LiveServer:
    base_url: str
    database_url: str


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


@pytest.fixture(scope="session")
def live_server() -> Generator[LiveServer, None, None]:
    """Boots a real Postgres container and a real uvicorn process running the
    actual FastAPI app against it -- not a TestClient, not mocked frontend
    state. Synthetic test-account provisioning is enabled so tests can log
    in through the real /api/auth/login flow with real, randomly generated
    credentials. Session-scoped: one boot serves every test in this
    directory, torn down once at the end.
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
            "OPTIMUS_TEST_ACCOUNT_PROVISIONING": "true",
            "OPENAI_API_KEY": "e2e-test-placeholder",
            "FRONTEND_ORIGIN": f"http://127.0.0.1:{_APP_PORT}",
        }
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=True, env=env)

        server_process = subprocess.Popen(
            [
                "uv",
                "run",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(_APP_PORT),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base_url = f"http://127.0.0.1:{_APP_PORT}"
            _wait_for(
                lambda: httpx.get(f"{base_url}/health", timeout=2).status_code == 200,
                timeout_seconds=30,
                description="the live app server to become healthy",
            )
            yield LiveServer(base_url=base_url, database_url=_DATABASE_URL)
        finally:
            server_process.terminate()
            try:
                server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_process.kill()
    finally:
        subprocess.run(["docker", "rm", "-f", _PG_CONTAINER], capture_output=True, check=False)


@dataclass(frozen=True, slots=True)
class SyntheticCredentials:
    user_id: int
    username: str
    password: str


@pytest.fixture
def synthetic_owner(live_server: LiveServer) -> Generator[SyntheticCredentials, None, None]:
    response = httpx.post(f"{live_server.base_url}/api/test-support/synthetic-owner", timeout=10)
    response.raise_for_status()
    body = response.json()
    credentials = SyntheticCredentials(
        user_id=body["user_id"], username=body["username"], password=body["password"]
    )
    try:
        yield credentials
    finally:
        # raise_for_status() here matters: this call previously failed
        # silently (fire-and-forget) whenever a test created Scheduling data
        # for this owner, because of a real FK-ordering bug in
        # `app/test_support_store.py::_delete_owner_and_dependents` (fixed
        # alongside `tests/e2e/test_scheduling_concurrency.py`) -- a
        # regression here should fail loudly, not leave synthetic data
        # behind unnoticed for the rest of the session.
        cleanup_response = httpx.delete(
            f"{live_server.base_url}/api/test-support/synthetic-accounts/{credentials.user_id}",
            timeout=10,
        )
        cleanup_response.raise_for_status()


@pytest.fixture
def synthetic_technician(
    live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> SyntheticCredentials:
    response = httpx.post(
        f"{live_server.base_url}/api/test-support/synthetic-technician",
        json={"owner_username": synthetic_owner.username},
        timeout=10,
    )
    response.raise_for_status()
    body = response.json()
    # Cleaned up automatically when synthetic_owner is deleted (cascades).
    return SyntheticCredentials(
        user_id=body["user_id"], username=body["username"], password=body["password"]
    )
