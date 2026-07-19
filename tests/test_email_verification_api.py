from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.auth import hash_password, require_authenticated_user, require_owner_context
from app.db_models import EmailVerificationToken, UserAccount
from app.email_verification_store import EmailVerificationError, request_email_verification
from app.models import VerifyEmailRequest
from app.services.email import EmailMessage, LoggingEmailAdapter
from tests.test_api import request_for
from tests.test_context_api import auth_context, raw_cookie_from_response
from tests.test_signup_api import signup

pytestmark = pytest.mark.anyio


class RecordingEmailAdapter:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.messages.append(message)


def _use_recording_adapter(monkeypatch: pytest.MonkeyPatch) -> RecordingEmailAdapter:
    adapter = RecordingEmailAdapter()
    monkeypatch.setattr(main, "email_adapter", lambda: adapter)
    return adapter


def _extract_token(message: EmailMessage) -> str:
    match = re.search(r"\n\n([A-Za-z0-9_-]{20,})\n\n", message.body)
    assert match is not None, f"Could not find a token in email body: {message.body!r}"
    return match.group(1)


async def _verify(db_session: Session, token: str, settings) -> dict[str, bool]:
    return await main.verify_email(
        VerifyEmailRequest(token=token),
        request_for("/api/auth/verify-email", method="POST"),
        db_session,
        settings,
    )


async def test_signup_automatically_requests_email_verification(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _use_recording_adapter(monkeypatch)
    payload, _response = await signup(settings, db_session)

    owner = db_session.scalar(select(UserAccount).where(UserAccount.id == payload["user"]["id"]))
    assert owner is not None
    assert owner.email_verified_at is None

    token_record = db_session.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.user_account_id == owner.id)
    )
    assert token_record is not None
    assert token_record.status == "active"

    assert len(adapter.messages) == 1
    assert adapter.messages[0].to == owner.email


async def test_verify_email_with_valid_token_marks_account_verified(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _use_recording_adapter(monkeypatch)
    payload, _response = await signup(settings, db_session)
    token = _extract_token(adapter.messages[0])

    result = await _verify(db_session, token, settings)
    assert result == {"verified": True}

    owner = db_session.scalar(select(UserAccount).where(UserAccount.id == payload["user"]["id"]))
    assert owner is not None
    assert owner.email_verified_at is not None

    token_record = db_session.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.user_account_id == owner.id)
    )
    assert token_record is not None
    assert token_record.status == "used"
    assert token_record.used_at is not None


async def test_verify_email_rejects_unknown_token(settings, db_session: Session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await _verify(db_session, "not-a-real-token-at-all-00000000", settings)
    assert excinfo.value.status_code == 422


async def test_verify_email_rejects_a_reused_token(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _use_recording_adapter(monkeypatch)
    await signup(settings, db_session)
    token = _extract_token(adapter.messages[0])

    await _verify(db_session, token, settings)
    with pytest.raises(HTTPException) as excinfo:
        await _verify(db_session, token, settings)
    assert excinfo.value.status_code == 422


async def test_verify_email_rejects_an_expired_token(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _use_recording_adapter(monkeypatch)
    await signup(settings, db_session)
    token = _extract_token(adapter.messages[0])

    token_record = db_session.scalar(select(EmailVerificationToken))
    assert token_record is not None
    token_record.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.add(token_record)
    db_session.commit()

    with pytest.raises(HTTPException) as excinfo:
        await _verify(db_session, token, settings)
    assert excinfo.value.status_code == 422

    db_session.refresh(token_record)
    assert token_record.status == "expired"


async def test_resend_email_verification_revokes_prior_token_and_issues_a_new_one(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _use_recording_adapter(monkeypatch)
    _payload, response = await signup(settings, db_session)
    first_token = _extract_token(adapter.messages[0])
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    result = await main.resend_email_verification(
        request_for("/api/auth/verify-email/resend", method="POST"),
        db_session,
        settings,
        owner_auth,
    )
    assert result == {"sent": True}
    assert len(adapter.messages) == 2
    second_token = _extract_token(adapter.messages[1])
    assert second_token != first_token

    # The first (pre-resend) token must no longer work.
    with pytest.raises(HTTPException) as excinfo:
        await _verify(db_session, first_token, settings)
    assert excinfo.value.status_code == 422

    # The new token must work.
    result = await _verify(db_session, second_token, settings)
    assert result == {"verified": True}


async def test_resend_email_verification_rejects_when_already_verified(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _use_recording_adapter(monkeypatch)
    _payload, response = await signup(settings, db_session)
    token = _extract_token(adapter.messages[0])
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    await _verify(db_session, token, settings)

    with pytest.raises(HTTPException) as excinfo:
        await main.resend_email_verification(
            request_for("/api/auth/verify-email/resend", method="POST"),
            db_session,
            settings,
            owner_auth,
        )
    assert excinfo.value.status_code == 422


async def test_resend_email_verification_rate_limit_returns_429(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    _use_recording_adapter(monkeypatch)
    limited_settings = settings.model_copy(
        update={"max_email_verification_resend_attempts_per_hour": 1}
    )
    _payload, response = await signup(limited_settings, db_session)
    owner_auth = auth_context(limited_settings, db_session, raw_cookie_from_response(response))

    # Signup's own auto-request doesn't share this limiter (it isn't a
    # "resend"), so this first explicit resend is attempt 1 against this
    # limiter and should succeed; the very next call must 429.
    await main.resend_email_verification(
        request_for("/api/auth/verify-email/resend", method="POST"),
        db_session,
        limited_settings,
        owner_auth,
    )
    with (
        caplog.at_level(logging.WARNING, logger="optimus"),
        pytest.raises(HTTPException) as excinfo,
    ):
        await main.resend_email_verification(
            request_for("/api/auth/verify-email/resend", method="POST"),
            db_session,
            limited_settings,
            owner_auth,
        )
    assert excinfo.value.status_code == 429
    assert "security event: rate_limit.exceeded" in caplog.text


async def test_email_verification_confirmation_rate_limit_returns_429(
    settings, db_session: Session, caplog
) -> None:
    limited_settings = settings.model_copy(update={"max_email_verification_attempts_per_minute": 1})

    with pytest.raises(HTTPException) as first_attempt:
        await _verify(db_session, "invalid-verification-token-00000001", limited_settings)
    assert first_attempt.value.status_code == 422

    with (
        caplog.at_level(logging.WARNING, logger="optimus"),
        pytest.raises(HTTPException) as second_attempt,
    ):
        await _verify(db_session, "invalid-verification-token-00000002", limited_settings)
    assert second_attempt.value.status_code == 429
    assert "security event: rate_limit.exceeded" in caplog.text


async def test_unverified_signup_session_is_limited_until_email_is_confirmed(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = _use_recording_adapter(monkeypatch)
    _payload, response = await signup(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    with pytest.raises(HTTPException) as owner_denial:
        require_owner_context(owner_auth, db_session)
    assert owner_denial.value.status_code == 403

    with pytest.raises(HTTPException) as authenticated_denial:
        require_authenticated_user(owner_auth)
    assert authenticated_denial.value.status_code == 403

    await _verify(db_session, _extract_token(adapter.messages[0]), settings)
    db_session.refresh(owner_auth.user)

    assert require_owner_context(owner_auth, db_session) is owner_auth
    assert require_authenticated_user(owner_auth) is owner_auth.user


async def test_request_email_verification_rejects_account_with_no_email(
    settings, db_session: Session
) -> None:
    owner_with_no_email = UserAccount(
        username="no-email-owner",
        display_name="No Email Owner",
        role="owner",
        password_hash=hash_password("owner-password-123"),
        is_active=True,
    )
    db_session.add(owner_with_no_email)
    db_session.commit()

    with pytest.raises(EmailVerificationError):
        request_email_verification(db_session, settings, owner_with_no_email, LoggingEmailAdapter())


def test_logging_email_adapter_never_logs_message_body_or_token(caplog) -> None:
    raw_token = "verification-token-that-must-never-appear-in-logs"
    message = EmailMessage(
        to="owner@example.com",
        subject="Verify your email",
        body=f"Use this code: {raw_token}",
    )

    with caplog.at_level(logging.INFO, logger="optimus"):
        LoggingEmailAdapter().send(message)

    assert "owner@example.com" not in caplog.text
    assert "Verify your email" in caplog.text
    assert raw_token not in caplog.text
    assert message.body not in caplog.text


def test_only_one_active_verification_token_is_allowed_per_account(
    settings, db_session: Session
) -> None:
    owner = UserAccount(
        username="active-token-owner",
        display_name="Active Token Owner",
        role="owner",
        email="active-token@example.com",
        email_normalized="active-token@example.com",
        password_hash=hash_password("owner-password-123"),
        is_active=True,
    )
    db_session.add(owner)
    db_session.commit()

    request_email_verification(db_session, settings, owner, RecordingEmailAdapter())
    request_email_verification(db_session, settings, owner, RecordingEmailAdapter())

    records = db_session.scalars(
        select(EmailVerificationToken).where(EmailVerificationToken.user_account_id == owner.id)
    ).all()
    assert [record.status for record in records].count("active") == 1
    assert [record.status for record in records].count("revoked") == 1
