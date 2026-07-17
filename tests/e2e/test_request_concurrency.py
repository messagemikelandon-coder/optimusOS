from __future__ import annotations

import threading
import time

import httpx

from tests.e2e.conftest import LiveServer, SyntheticCredentials


def test_two_simultaneous_requests_genuinely_overlap(live_server: LiveServer) -> None:
    """Phase 1 of the /goal roadmap: proves request-level concurrency is
    fixed, not just that the fix's code exists. Before this fix, every
    route was `async def` but called a blocking, synchronous store
    function directly with no thread-pool offload, and the real
    `Dockerfile` runs a single `uvicorn` worker -- confirmed empirically
    this session (a deliberate 1s delay inserted into a store function
    made two "concurrent" requests take ~2s total, not ~1s). Every route
    now offloads its blocking work via `asyncio.to_thread`
    (`app/main.py`), which should let two simultaneous requests' blocking
    work genuinely overlap within one process.

    Uses a shared in-flight counter (`/api/test-support/concurrency-probe`)
    rather than a wall-clock timing threshold, since timing assertions are
    flaky under real scheduling jitter -- a counter reaching 2 is
    unambiguous proof of overlap; never reaching 2 is unambiguous proof of
    serialization, regardless of how fast or slow the underlying machine
    is."""
    client = httpx.Client(base_url=live_server.base_url, timeout=10)
    reset_response = client.post("/api/test-support/concurrency-probe/reset")
    assert reset_response.status_code == 204

    results: list[int] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(3)

    def _probe() -> None:
        with httpx.Client(base_url=live_server.base_url, timeout=10) as thread_client:
            barrier.wait()
            response = thread_client.get(
                "/api/test-support/concurrency-probe", params={"delay_ms": 300}
            )
            response.raise_for_status()
            with results_lock:
                results.append(response.json()["max_observed_in_flight"])

    threads = [threading.Thread(target=_probe) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 3
    assert max(results) >= 2, (
        f"Expected at least 2 of the 3 simultaneous probe requests to genuinely "
        f"overlap in flight at once, got max_observed_in_flight results: {results}. "
        "This would mean request handling is still serialized."
    )


def _login(live_server: LiveServer, creds: SyntheticCredentials) -> httpx.Client:
    client = httpx.Client(base_url=live_server.base_url, timeout=10)
    response = client.post(
        "/api/auth/login", json={"username": creds.username, "password": creds.password}
    )
    response.raise_for_status()
    return client


def test_simultaneous_owner_and_technician_requests_do_not_serialize(
    live_server: LiveServer,
    synthetic_owner: SyntheticCredentials,
    synthetic_technician: SyntheticCredentials,
) -> None:
    """Load test required by Phase 1 of the /goal roadmap: real,
    concurrently-issued, differently-authenticated (owner vs. technician)
    requests must not block each other. Self-calibrating rather than
    threshold-based -- measures a sequential baseline on this same machine
    first, then asserts the concurrent run is meaningfully faster than that
    baseline, so the test isn't sensitive to how fast or slow the CI
    runner happens to be."""
    owner_client = _login(live_server, synthetic_owner)
    technician_client = _login(live_server, synthetic_technician)

    owner_request = ("owner", owner_client, "/api/work-orders")
    technician_request = ("technician", technician_client, "/api/technicians/me")
    requests = [owner_request, technician_request, owner_request, technician_request]

    def _fire(role: str, client: httpx.Client, path: str) -> tuple[str, int]:
        response = client.get(path)
        return role, response.status_code

    # Sequential baseline: same 4 requests, run one at a time.
    sequential_start = time.monotonic()
    sequential_results = [_fire(role, client, path) for role, client, path in requests]
    sequential_duration = time.monotonic() - sequential_start

    assert all(status == 200 for _role, status in sequential_results)

    # Concurrent run: identical requests, fired from a shared barrier.
    concurrent_results: list[tuple[str, int]] = []
    concurrent_lock = threading.Lock()
    barrier = threading.Barrier(len(requests))

    def _fire_concurrent(role: str, client: httpx.Client, path: str) -> None:
        barrier.wait()
        result = _fire(role, client, path)
        with concurrent_lock:
            concurrent_results.append(result)

    threads = [
        threading.Thread(target=_fire_concurrent, args=(role, client, path))
        for role, client, path in requests
    ]
    concurrent_start = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    concurrent_duration = time.monotonic() - concurrent_start

    assert len(concurrent_results) == len(requests)
    assert all(status == 200 for _role, status in concurrent_results), concurrent_results

    # Generous margin (concurrent should be well under sequential, but this
    # isn't a tight race -- just needs to show real overlap happened).
    assert concurrent_duration < sequential_duration * 0.8, (
        f"Concurrent owner+technician requests took {concurrent_duration:.3f}s, "
        f"not meaningfully faster than the {sequential_duration:.3f}s sequential "
        "baseline on this same machine -- requests may still be serializing."
    )
