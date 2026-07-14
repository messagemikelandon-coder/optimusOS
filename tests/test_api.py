from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

import app.main as main
from app.auth import AuthContext, get_current_auth_context
from app.db_models import UserAccount
from app.models import (
    AuthLoginRequest,
    ChatRequest,
    ConversationMode,
    EstimateCreate,
    LocationInput,
)


def request_for(
    path: str,
    *,
    method: str = "GET",
    cookie_header: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = [(b"user-agent", b"pytest")]
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "scheme": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
    )


async def login(
    settings,
    db_session: Session,
    *,
    password: str = "owner-password-123",
) -> tuple[dict[str, Any], Response]:
    response = Response()
    payload = await main.login(
        AuthLoginRequest(username="owner", password=password),
        request_for("/api/auth/login", method="POST"),
        response,
        db_session,
        settings,
    )
    return payload.model_dump(mode="json"), response


def auth_context(settings, db_session: Session, raw_cookie: str) -> AuthContext:
    return get_current_auth_context(
        request_for("/api/auth/me", cookie_header=f"{settings.session_cookie_name}={raw_cookie}"),
        db_session,
        settings,
    )


@pytest.mark.anyio
async def test_health(settings) -> None:  # type: ignore[no-untyped-def]
    payload = await main.health(settings)
    assert payload["status"] == "ok"
    assert payload["auth_configured"] is True
    assert payload["migration_head"]
    assert payload["git_commit"]  # "unknown" in this dev/test environment, but always present


@pytest.mark.anyio
async def test_ready_reports_dependency_and_schema_state(monkeypatch, settings) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main, "_tcp_dependency_ready", lambda url, default_port: True)
    payload = await main.ready(settings)
    assert payload["status"] == "ready"
    assert payload["dependencies"] == {"postgres": True, "redis": True}
    assert payload["migration_head"]
    # The test schema is built directly from the ORM (Base.metadata.create_all),
    # not via Alembic, so there's genuinely no alembic_version table here --
    # correctly reported as "unmigrated", not silently ignored.
    assert payload["schema_compatibility"] == "unmigrated"


@pytest.mark.anyio
async def test_ready_degrades_when_the_database_schema_is_unsupported(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main, "_tcp_dependency_ready", lambda url, default_port: True)
    db_session.execute(select(1))  # ensure the shared in-memory engine/connection is already open
    db_session.connection().exec_driver_sql(
        "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
    )
    db_session.connection().exec_driver_sql(
        "INSERT INTO alembic_version (version_num) VALUES ('999_totally_unknown_revision')"
    )
    db_session.commit()

    payload = await main.ready(settings)
    assert payload["status"] == "degraded"
    assert payload["schema_compatibility"] == "unsupported"
    assert payload["database_migration_revision"] == "999_totally_unknown_revision"


@pytest.mark.anyio
async def test_login_sets_http_only_cookie_and_me_restores_session(
    settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    payload, response = await login(settings, db_session)
    assert payload["user"]["username"] == "owner"
    assert payload["user"]["role"] == "owner"
    assert payload["session_expires_in_seconds"] > 0

    set_cookie = response.headers["set-cookie"]
    assert "optimus_session=" in set_cookie
    assert "HttpOnly" in set_cookie

    user = db_session.scalar(select(UserAccount).where(UserAccount.username == "owner"))
    assert user is not None
    raw_cookie = response.headers["set-cookie"].split("optimus_session=", 1)[1].split(";", 1)[0]
    me = await main.auth_me(auth_context(settings, db_session, raw_cookie))
    assert me.user.username == "owner"


@pytest.mark.anyio
async def test_login_rejects_invalid_credentials(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as excinfo:
        await login(settings, db_session, password="wrong-password")
    assert excinfo.value.status_code == 401


@pytest.mark.anyio
async def test_logout_revokes_session(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, login_response = await login(settings, db_session)
    raw_cookie = (
        login_response.headers["set-cookie"].split("optimus_session=", 1)[1].split(";", 1)[0]
    )
    response = Response()
    result = await main.logout(
        response, db_session, settings, auth_context(settings, db_session, raw_cookie)
    )
    assert result == {"ok": True}

    with pytest.raises(HTTPException) as excinfo:
        auth_context(settings, db_session, raw_cookie)
    assert excinfo.value.status_code == 401


def test_estimate_requires_authenticated_session(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as excinfo:
        get_current_auth_context(request_for("/api/estimates"), db_session, settings)
    assert excinfo.value.status_code == 401


@pytest.mark.anyio
async def test_estimate_requires_api_key_after_authentication(
    settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    settings.openai_api_key = ""
    _, response = await login(settings, db_session)
    raw_cookie = response.headers["set-cookie"].split("optimus_session=", 1)[1].split(";", 1)[0]
    auth = auth_context(settings, db_session, raw_cookie)
    with pytest.raises(HTTPException) as excinfo:
        await main.create_estimate_record(
            EstimateCreate(
                customer_id=1,
                vehicle_id=1,
                job="Oil change",
                location=LocationInput(postal_code="66442"),
            ),
            db_session,
            settings,
            auth,
        )
    assert excinfo.value.status_code == 503


@pytest.mark.anyio
async def test_chat_requires_api_key_after_authentication(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    settings.openai_api_key = ""
    _, response = await login(settings, db_session)
    raw_cookie = response.headers["set-cookie"].split("optimus_session=", 1)[1].split(";", 1)[0]
    current_user = auth_context(settings, db_session, raw_cookie).user
    with pytest.raises(HTTPException) as excinfo:
        await main.chat(
            ChatRequest(message="Look up a starter price", mode=ConversationMode.DIRECT),
            request_for("/api/chat", method="POST"),
            settings,
            current_user,
        )
    assert excinfo.value.status_code == 503


@pytest.mark.anyio
async def test_estimate_returns_safe_structured_upstream_error(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    from app.errors import EstimatorResearchError
    from app.orchestrator import OptimusResearchOrchestrator
    from tests.test_vehicles_api import create_customer_for_auth, vehicle_payload

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
    _, response = await login(settings, db_session)
    raw_cookie = response.headers["set-cookie"].split("optimus_session=", 1)[1].split(";", 1)[0]
    auth = auth_context(settings, db_session, raw_cookie)
    customer_id = await create_customer_for_auth(settings, db_session, auth)
    vehicle = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)
    with pytest.raises(HTTPException) as excinfo:
        await main.create_estimate_record(
            EstimateCreate(
                customer_id=customer_id,
                vehicle_id=vehicle.id,
                job="Replace front brakes",
                location=LocationInput(postal_code="95677"),
            ),
            db_session,
            settings,
            auth,
        )
    assert excinfo.value.status_code == 504
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    detail_dict = cast(dict[str, object], detail)
    assert detail_dict["code"] == "openai_timeout"
    assert detail_dict["request_id"] == "abc123"
    assert "API key" not in str(detail)
