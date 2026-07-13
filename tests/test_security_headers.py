from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main


def test_hsts_header_absent_over_local_http_origin() -> None:
    """Sending HSTS over a plain-HTTP local origin would tell browsers to
    demand HTTPS on a host that can't serve it -- must stay absent locally."""
    settings = main.get_settings()
    assert not settings.frontend_origin.lower().startswith("https://")
    client = TestClient(main.app)
    response = client.get("/health")
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_header_present_when_frontend_origin_is_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_settings = main.get_settings()
    https_settings = original_settings.model_copy(
        update={"frontend_origin": "https://staging.example.com"}
    )
    monkeypatch.setattr(main, "get_settings", lambda: https_settings)
    client = TestClient(main.app)
    response = client.get("/health")
    assert response.headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains"


def test_baseline_security_headers_present_on_every_response() -> None:
    client = TestClient(main.app)
    response = client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "Content-Security-Policy" in response.headers
