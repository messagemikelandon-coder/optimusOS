from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.db import get_db_session, get_settings
from app.observability import JsonLogFormatter, RequestIdLogFilter, request_id_var

pytestmark = pytest.mark.anyio

_SECRET_PASSWORD = "correct-horse-battery-staple-999"
_SECRET_TOKEN = "sk-forbidden-fixture-token-999"


def test_json_log_formatter_produces_valid_json_with_expected_fields() -> None:
    record = logging.LogRecord(
        name="optimus",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=(),
        exc_info=None,
    )
    record.http_method = "GET"
    record.http_path = "/health"
    record.http_status_code = 200
    record.duration_ms = 1.23
    record.request_id = "fixture-request-id"

    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["message"] == "request completed"
    assert payload["request_id"] == "fixture-request-id"
    assert payload["http_method"] == "GET"
    assert payload["http_path"] == "/health"
    assert payload["http_status_code"] == 200
    assert payload["duration_ms"] == 1.23


def test_request_id_log_filter_attaches_the_current_contextvar() -> None:
    token = request_id_var.set("fixture-context-request-id")
    try:
        record = logging.LogRecord(
            name="optimus",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="some log from deep inside a store function",
            args=(),
            exc_info=None,
        )
        assert RequestIdLogFilter().filter(record) is True
        assert getattr(record, "request_id", None) == "fixture-context-request-id"
    finally:
        request_id_var.reset(token)


def test_response_includes_a_real_request_id_header(settings, db_session) -> None:  # type: ignore[no-untyped-def]
    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        response = client.get("/health")
        assert response.status_code == 200
        request_id = response.headers.get("x-request-id")
        assert request_id
        # Two requests must not reuse the same id.
        assert client.get("/health").headers["x-request-id"] != request_id
    finally:
        main.app.dependency_overrides.clear()


def test_login_request_with_a_real_password_never_appears_in_any_log_record(
    caplog, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    """The structured request-logging middleware only ever logs
    method/path/status/duration/request_id -- never the request body. This
    proves that end to end: a real login attempt carrying a real-looking
    password (and, separately, a request carrying an OpenAI-key-shaped
    value in a header) must never surface that value in any log record
    emitted anywhere during the request, not just the middleware's own."""
    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        with caplog.at_level(logging.DEBUG):
            client.post(
                "/api/auth/login",
                json={"username": "nonexistent-user", "password": _SECRET_PASSWORD},
                headers={"X-Probe-Token": _SECRET_TOKEN},
            )
        for record in caplog.records:
            rendered = record.getMessage()
            assert _SECRET_PASSWORD not in rendered
            assert _SECRET_TOKEN not in rendered
            for value in getattr(record, "__dict__", {}).values():
                assert _SECRET_PASSWORD not in str(value)
                assert _SECRET_TOKEN not in str(value)
    finally:
        main.app.dependency_overrides.clear()
