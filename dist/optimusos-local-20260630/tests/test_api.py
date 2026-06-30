from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_reports_dependency_state(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import app.main as main

    monkeypatch.setattr(main, "_tcp_dependency_ready", lambda url, default_port: True)
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["dependencies"] == {"postgres": True, "redis": True}


def test_estimate_requires_api_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.config import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(openai_api_key="")
    try:
        client = TestClient(app)
        response = client.post(
            "/api/estimate",
            json={
                "vehicle": {"year": 2018, "make": "Honda", "model": "CR-V"},
                "job": "Oil change",
                "location": {"postal_code": "66442"},
            },
        )
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_chat_requires_api_key() -> None:
    from app.config import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(openai_api_key="")
    try:
        client = TestClient(app)
        response = client.post(
            "/api/chat",
            json={"message": "Look up a starter price", "mode": "direct"},
        )
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_estimate_returns_safe_structured_upstream_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.config import Settings, get_settings
    from app.errors import EstimatorResearchError
    from app.orchestrator import OptimusResearchOrchestrator

    async def fail_estimate(self, request):  # type: ignore[no-untyped-def]
        del self, request
        raise EstimatorResearchError(
            code="openai_timeout",
            message="The live labor-and-parts research request timed out.",
            stage="structured_web_research",
            request_id="abc123",
            http_status=504,
        )

    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", fail_estimate)
    app.dependency_overrides[get_settings] = lambda: Settings(openai_api_key="test")
    try:
        client = TestClient(app)
        response = client.post(
            "/api/estimate",
            json={
                "vehicle": {"year": 2018, "make": "Honda", "model": "CR-V"},
                "job": "Replace front brakes",
                "location": {"postal_code": "95677"},
            },
        )
        assert response.status_code == 504
        detail = response.json()["detail"]
        assert detail["code"] == "openai_timeout"
        assert detail["request_id"] == "abc123"
        assert "API key" not in str(detail)
    finally:
        app.dependency_overrides.clear()
