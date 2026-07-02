from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

import app.main as main
from app.auth import AuthContext, get_current_auth_context, hash_password
from app.db_models import ContextEntry, UserAccount
from app.models import AuthLoginRequest, ContextEntryUpsertRequest, ContextScope
from tests.test_api import request_for


async def login_as(
    settings,
    db_session: Session,
    *,
    username: str = "owner",
    password: str = "owner-password-123",
) -> tuple[dict[str, object], Response]:
    response = Response()
    payload = await main.login(
        AuthLoginRequest(username=username, password=password),
        request_for("/api/auth/login", method="POST"),
        response,
        db_session,
        settings,
    )
    return payload.model_dump(mode="json"), response


def auth_context(settings, db_session: Session, raw_cookie: str) -> AuthContext:
    return get_current_auth_context(
        request_for(
            "/api/auth/me",
            cookie_header=f"{settings.session_cookie_name}={raw_cookie}",
        ),
        db_session,
        settings,
    )


def raw_cookie_from_response(response: Response) -> str:
    return response.headers["set-cookie"].split("optimus_session=", 1)[1].split(";", 1)[0]


def create_user(db_session: Session, *, username: str, password: str) -> UserAccount:
    user = UserAccount(
        username=username,
        display_name=username.title(),
        role="owner",
        password_hash=hash_password(password),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.mark.anyio
async def test_context_requires_authenticated_session(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as excinfo:
        get_current_auth_context(request_for("/api/context/project-a"), db_session, settings)
    assert excinfo.value.status_code == 401


@pytest.mark.anyio
async def test_context_create_read_update_and_delete(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    created = await main.put_context(
        "project-a",
        "repair-plan",
        ContextEntryUpsertRequest(value="Initial note"),
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )
    assert created.revision == 1

    listed = await main.get_context(
        "project-a",
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )
    assert [entry.context_key for entry in listed.entries] == ["repair-plan"]
    assert listed.entries[0].value == "Initial note"

    updated = await main.put_context(
        "project-a",
        "repair-plan",
        ContextEntryUpsertRequest(value="Updated note", expected_revision=1),
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )
    assert updated.revision == 2

    deleted = await main.remove_context(
        "project-a",
        "repair-plan",
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
        expected_revision=2,
    )
    assert deleted.deleted_revision == 2

    empty = await main.get_context(
        "project-a",
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )
    assert empty.entries == []


@pytest.mark.anyio
async def test_context_conflict_returns_deterministic_error(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    await main.put_context(
        "project-a",
        "shared",
        ContextEntryUpsertRequest(value="v1"),
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.put_context(
            "project-a",
            "shared",
            ContextEntryUpsertRequest(value="v2", expected_revision=7),
            db_session,
            settings,
            auth,
            ContextScope.PROJECT,
        )
    assert excinfo.value.status_code == 409
    assert "revision mismatch" in str(excinfo.value.detail).lower()


@pytest.mark.anyio
async def test_session_scope_overrides_project_scope_with_fallback(
    settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    await main.put_context(
        "project-a",
        "shared",
        ContextEntryUpsertRequest(value="project-default"),
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )
    await main.put_context(
        "project-a",
        "project-only",
        ContextEntryUpsertRequest(value="project-only-value"),
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )
    await main.put_context(
        "project-a",
        "shared",
        ContextEntryUpsertRequest(value="session-override"),
        db_session,
        settings,
        auth,
        ContextScope.SESSION,
    )
    await main.put_context(
        "project-a",
        "session-only",
        ContextEntryUpsertRequest(value="session-only-value"),
        db_session,
        settings,
        auth,
        ContextScope.SESSION,
    )

    listed = await main.get_context(
        "project-a",
        db_session,
        settings,
        auth,
        ContextScope.SESSION,
    )

    values = {entry.context_key: entry.value for entry in listed.entries}
    scopes = {entry.context_key: entry.scope for entry in listed.entries}
    assert values == {
        "shared": "session-override",
        "session-only": "session-only-value",
        "project-only": "project-only-value",
    }
    assert scopes["shared"] is ContextScope.SESSION
    assert scopes["session-only"] is ContextScope.SESSION
    assert scopes["project-only"] is ContextScope.PROJECT
    assert len([entry for entry in listed.entries if entry.context_key == "shared"]) == 1


@pytest.mark.anyio
async def test_session_scoped_entries_do_not_leak_between_sessions(
    settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response_one = await login_as(settings, db_session)
    _, response_two = await login_as(settings, db_session)
    auth_one = auth_context(settings, db_session, raw_cookie_from_response(response_one))
    auth_two = auth_context(settings, db_session, raw_cookie_from_response(response_two))

    await main.put_context(
        "project-a",
        "session-note",
        ContextEntryUpsertRequest(value="visible-in-session-one"),
        db_session,
        settings,
        auth_one,
        ContextScope.SESSION,
    )

    listed = await main.get_context(
        "project-a",
        db_session,
        settings,
        auth_two,
        ContextScope.SESSION,
    )
    assert listed.entries == []


@pytest.mark.anyio
async def test_project_scoped_entries_do_not_leak_between_projects(
    settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    await main.put_context(
        "project-a",
        "note",
        ContextEntryUpsertRequest(value="project-a-only"),
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )

    listed = await main.get_context(
        "project-b",
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )
    assert listed.entries == []


@pytest.mark.anyio
async def test_context_isolated_between_users(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    create_user(db_session, username="other", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings,
        db_session,
        username="other",
        password="other-password-123",
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    await main.put_context(
        "project-a",
        "note",
        ContextEntryUpsertRequest(value="owner-only"),
        db_session,
        settings,
        owner_auth,
        ContextScope.PROJECT,
    )

    other_list = await main.get_context(
        "project-a",
        db_session,
        settings,
        other_auth,
        ContextScope.PROJECT,
    )
    assert other_list.entries == []

    with pytest.raises(HTTPException) as excinfo:
        await main.remove_context(
            "project-a",
            "note",
            db_session,
            settings,
            other_auth,
            ContextScope.PROJECT,
        )
    assert excinfo.value.status_code == 404


@pytest.mark.anyio
async def test_context_entry_count_limit_is_enforced(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    settings.context_max_entries_per_scope = 2
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    await main.put_context(
        "project-a",
        "one",
        ContextEntryUpsertRequest(value="first"),
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )
    await main.put_context(
        "project-a",
        "two",
        ContextEntryUpsertRequest(value="second"),
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.put_context(
            "project-a",
            "three",
            ContextEntryUpsertRequest(value="third"),
            db_session,
            settings,
            auth,
            ContextScope.PROJECT,
        )
    assert excinfo.value.status_code == 409


@pytest.mark.anyio
async def test_context_value_size_boundaries(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    settings.context_max_value_chars = 8
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    created = await main.put_context(
        "project-a",
        "limit",
        ContextEntryUpsertRequest(value="12345678"),
        db_session,
        settings,
        auth,
        ContextScope.PROJECT,
    )
    assert created.value == "12345678"

    with pytest.raises(HTTPException) as excinfo:
        await main.put_context(
            "project-a",
            "too-large",
            ContextEntryUpsertRequest(value="123456789"),
            db_session,
            settings,
            auth,
            ContextScope.PROJECT,
        )
    assert excinfo.value.status_code == 422
    assert "character limit" in str(excinfo.value.detail).lower()


@pytest.mark.anyio
async def test_secret_like_values_are_rejected_without_persistence_or_log_leakage(
    settings, db_session: Session, caplog
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    secret_value = "Bearer secret-token-value-1234567890"

    with (
        caplog.at_level(logging.WARNING, logger="optimus"),
        pytest.raises(HTTPException) as excinfo,
    ):
        await main.put_context(
            "project-a",
            "secret",
            ContextEntryUpsertRequest(value=secret_value),
            db_session,
            settings,
            auth,
            ContextScope.PROJECT,
        )
    assert excinfo.value.status_code == 422
    assert secret_value not in str(excinfo.value.detail)
    assert secret_value not in caplog.text
    assert db_session.scalar(select(ContextEntry)) is None


@pytest.mark.anyio
async def test_context_storage_failures_are_sanitized_in_response_and_logs(
    monkeypatch, settings, db_session: Session, caplog
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    leaked_fragment = "raw-db-secret-123"

    def fail_upsert(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise SQLAlchemyError(leaked_fragment)

    monkeypatch.setattr(main, "upsert_entry", fail_upsert)

    with (
        caplog.at_level(logging.WARNING, logger="optimus"),
        pytest.raises(HTTPException) as excinfo,
    ):
        await main.put_context(
            "project-a",
            "note",
            ContextEntryUpsertRequest(value="safe"),
            db_session,
            settings,
            auth,
            ContextScope.PROJECT,
        )
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Context storage is unavailable."
    assert leaked_fragment not in caplog.text


@pytest.mark.anyio
async def test_auth_storage_failures_are_sanitized_in_response_and_logs(
    monkeypatch, settings, db_session: Session, caplog
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    leaked_fragment = "auth-storage-secret-456"

    def fail_scalar(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise SQLAlchemyError(leaked_fragment)

    monkeypatch.setattr(db_session, "scalar", fail_scalar)

    with (
        caplog.at_level(logging.WARNING, logger="optimus"),
        pytest.raises(HTTPException) as excinfo,
    ):
        auth_context(settings, db_session, raw_cookie_from_response(response))
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Authentication storage is unavailable."
    assert leaked_fragment not in caplog.text


@pytest.mark.anyio
async def test_missing_context_delete_returns_not_found(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    with pytest.raises(HTTPException) as excinfo:
        await main.remove_context(
            "project-a",
            "missing",
            db_session,
            settings,
            auth,
            ContextScope.PROJECT,
        )
    assert excinfo.value.status_code == 404


@pytest.mark.anyio
async def test_context_model_constraints_reject_invalid_cross_scope_rows(
    settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    db_session.add(
        ContextEntry(
            user_id=auth.user.id,
            auth_session_id=auth.session.id,
            project_key="project-a",
            scope_type="project",
            scope_key="project:project-a",
            context_key="invalid-project",
            value="bad",
            revision=1,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    db_session.add(
        ContextEntry(
            user_id=auth.user.id,
            auth_session_id=None,
            project_key="project-a",
            scope_type="session",
            scope_key=f"project:project-a:session:{auth.session.id}",
            context_key="invalid-session",
            value="bad",
            revision=1,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
