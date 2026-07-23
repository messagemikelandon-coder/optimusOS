"""The request-context middleware feeds the Phase 2B request-metrics registry.

Proves the middleware records one metric per request on the success path, uses
the matched route template (not the raw path) as the label, records a failed
request as a 500 while re-raising (never suppressing the exception), and labels
an unmatched (404) request with the sentinel.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability import install_request_context_middleware
from app.runtime_metrics import UNMATCHED_TEMPLATE, request_metrics


@pytest.fixture(autouse=True)
def _reset_metrics():
    request_metrics.reset()
    yield
    request_metrics.reset()


def _app() -> FastAPI:
    app = FastAPI()
    install_request_context_middleware(app, logging.getLogger("optimus.test"))

    @app.get("/api/items/{item_id}")
    async def get_item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("kaboom")

    return app


def test_success_records_route_template_not_raw_path() -> None:
    client = TestClient(_app())
    assert client.get("/api/items/42").status_code == 200
    snap = request_metrics.snapshot()
    assert snap.total_requests == 1
    assert snap.status_classes["success"] == 1
    route = snap.top_routes[0]
    # The label is the template with a placeholder, never the concrete id "42".
    assert route.route == "/api/items/{item_id}"
    assert "42" not in route.route
    assert route.method == "GET"


def test_failed_request_records_500_and_reraises() -> None:
    # raise_server_exceptions=True: the exception must propagate through the
    # middleware (it is never suppressed), and be counted as a server error.
    client = TestClient(_app(), raise_server_exceptions=True)
    with pytest.raises(RuntimeError):
        client.get("/boom")
    snap = request_metrics.snapshot()
    assert snap.total_requests == 1
    assert snap.status_classes["server_error"] == 1
    assert snap.top_routes[0].error_count == 1


def test_unmatched_request_uses_sentinel_label() -> None:
    client = TestClient(_app())
    assert client.get("/no/such/path").status_code == 404
    snap = request_metrics.snapshot()
    assert snap.total_requests == 1
    assert snap.status_classes["client_error"] == 1
    assert snap.top_routes[0].route == UNMATCHED_TEMPLATE
