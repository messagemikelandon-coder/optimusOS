from __future__ import annotations

import threading

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.auth import get_current_auth_context
from app.db import build_engine
from app.db_models import Estimate, JobCompilationEvent
from app.job_release import release_job_compilation
from tests.e2e.conftest import LiveServer, SyntheticCredentials
from tests.e2e.test_scheduling_concurrency import _login_client, _raw_cookie
from tests.test_api import request_for


def test_concurrent_release_of_same_compilation_creates_one_estimate(
    live_server: LiveServer, settings, synthetic_owner: SyntheticCredentials
) -> None:
    """Executable evidence for the release bridge's idempotency/transaction
    safety: two real Python threads (each its own Postgres session/transaction)
    releasing the SAME compilation concurrently must produce exactly one
    canonical estimate and exactly one ``released`` event -- never a duplicate.
    The ``SELECT ... FOR UPDATE`` row lock in ``release_job_compilation``
    serializes them; the second racer blocks until the first commits, then sees
    ``released_estimate_id`` already set and returns the existing estimate
    (``already_released=True``). SQLite (the fast suite) ignores ``FOR UPDATE``,
    so this real-Postgres test is where the lock is actually exercised."""
    owner_client = _login_client(live_server, synthetic_owner)

    customer_id = owner_client.post(
        "/api/customers", json={"first_name": "Race", "last_name": "Release"}
    ).json()["id"]
    vehicle_id = owner_client.post(
        f"/api/customers/{customer_id}/vehicles", json={"make": "Honda", "model": "Civic"}
    ).json()["id"]
    finding_id = owner_client.post(
        "/api/diagnostic-findings",
        json={
            "vehicle_id": vehicle_id,
            "symptoms": "Grinding when braking.",
            "conclusion": "Front pads worn out.",
            "confidence": "confirmed",
            "severity": "unsafe",
        },
    ).json()["id"]
    part_id = owner_client.post(
        "/api/parts",
        json={
            "part_number": "BP-RACE",
            "description": "Front brake pad set",
            "quantity_on_hand": 8,
            "unit_price": 48.0,
        },
    ).json()["id"]
    compile_response = owner_client.post(
        f"/api/diagnostic-findings/{finding_id}/compile-job",
        json={
            "labor_rate": 120.0,
            "services": [
                {
                    "title": "Replace front brake pads",
                    "labor_hours": 1.5,
                    "parts": [{"part_id": part_id, "quantity": 2}],
                }
            ],
        },
    )
    compile_response.raise_for_status()
    compilation_id = compile_response.json()["id"]

    raw_cookie = _raw_cookie(owner_client)
    engine = build_engine(live_server.database_url)
    thread_session_factory = sessionmaker(bind=engine)

    results: list[bool] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def _attempt_release() -> None:
        thread_db = thread_session_factory()
        try:
            thread_auth = get_current_auth_context(
                request_for(
                    "/api/auth/me",
                    cookie_header=f"{settings.session_cookie_name}={raw_cookie}",
                ),
                thread_db,
                settings,
            )
            barrier.wait()
            response = release_job_compilation(
                db=thread_db, auth=thread_auth, compilation_id=compilation_id
            )
            with results_lock:
                results.append(response.already_released)
        finally:
            thread_db.close()

    threads = [threading.Thread(target=_attempt_release) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Both calls succeed, but exactly one performed the release (the other saw
    # it already released) -- and there is exactly one estimate and one event.
    assert len(results) == 2
    assert results.count(False) == 1, f"Expected exactly one real release, got {results}"
    assert results.count(True) == 1

    verify_db = thread_session_factory()
    try:
        estimate_count = verify_db.scalar(select(func.count()).select_from(Estimate))
        released_events = verify_db.scalar(
            select(func.count())
            .select_from(JobCompilationEvent)
            .where(JobCompilationEvent.event_type == "released")
        )
    finally:
        verify_db.close()
    assert estimate_count == 1, f"Expected exactly one estimate, got {estimate_count}"
    assert released_events == 1, f"Expected exactly one released event, got {released_events}"
