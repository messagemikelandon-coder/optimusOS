from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.requests import Request

import app.account_security_store as account_security_store
import app.main as main
from app.account_security_store import (
    InvitationConflictError,
    InvitationError,
    MemberManagementError,
    PasswordResetTokenError,
    SessionNotFoundError,
    accept_invitation,
    authenticate_account,
    change_password,
    confirm_password_reset,
    create_invitation,
    list_invitations,
    list_members,
    list_sessions,
    login_history,
    request_password_reset,
    revoke_invitation,
    revoke_other_sessions,
    revoke_session,
    security_summary,
    update_member_status,
)
from app.auth import AuthContext, create_auth_session, verify_password
from app.db import get_db_session, get_settings
from app.db_models import (
    AuthMfaFactor,
    AuthSession,
    PasswordResetToken,
    ShopInvitation,
    ShopMembership,
    Technician,
    UserAccount,
)
from app.models import (
    AccountStatusUpdate,
    PasswordChangeRequest,
    ShopInvitationAccept,
    ShopInvitationCreate,
    ShopRole,
)
from app.rate_limit import SlidingWindowRateLimiter
from app.services.email import EmailMessage
from tests.test_api import request_for
from tests.test_context_api import create_user


class RecordingEmailAdapter:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.messages.append(message)


def _token_from_message(message: EmailMessage) -> str:
    match = re.search(r"\n\n([A-Za-z0-9_-]{20,})\n\n", message.body)
    assert match is not None
    return match.group(1)


def _auth_for(db: Session, user: UserAccount, suffix: str) -> AuthContext:
    session = AuthSession(
        user_id=user.id,
        token_hash=f"account-security-{user.id}-{suffix}",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_seen_at=datetime.now(UTC),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return AuthContext(user=user, session=session)


def _owner(db: Session) -> UserAccount:
    owner = db.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    return owner


def test_password_change_revokes_other_sessions_and_preserves_current(
    db_session: Session,
) -> None:
    owner = _owner(db_session)
    current = _auth_for(db_session, owner, "current")
    other = _auth_for(db_session, owner, "other")

    change_password(
        db_session,
        current,
        PasswordChangeRequest(
            current_password="owner-password-123",
            new_password="new-owner-password-456",
        ),
    )

    db_session.refresh(current.session)
    db_session.refresh(other.session)
    db_session.refresh(owner)
    assert current.session.revoked_at is None
    assert other.session.revoked_at is not None
    assert verify_password("new-owner-password-456", owner.password_hash)
    assert not verify_password("owner-password-123", owner.password_hash)


def test_password_change_revokes_outstanding_reset_tokens(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    owner.email = "change-reset@example.com"
    owner.email_normalized = "change-reset@example.com"
    owner.email_verified_at = datetime.now(UTC)
    db_session.add(owner)
    db_session.commit()
    adapter = RecordingEmailAdapter()
    request_password_reset(db_session, settings, "change-reset@example.com", adapter)
    token = _token_from_message(adapter.messages[0])
    auth = _auth_for(db_session, owner, "change-reset")
    change_password(
        db_session,
        auth,
        PasswordChangeRequest(
            current_password="owner-password-123",
            new_password="changed-reset-password-123",
        ),
    )
    record = db_session.scalar(select(PasswordResetToken))
    assert record is not None
    assert record.status == "revoked"
    with pytest.raises(PasswordResetTokenError):
        confirm_password_reset(db_session, token, "stolen-reset-password-123")


def test_password_reset_is_hash_only_single_use_and_revokes_sessions(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    owner.email = "owner@example.com"
    owner.email_normalized = "owner@example.com"
    owner.email_verified_at = datetime.now(UTC)
    db_session.add(owner)
    db_session.commit()
    auth = _auth_for(db_session, owner, "reset")
    adapter = RecordingEmailAdapter()

    owner_email = owner.email
    assert owner_email is not None
    request_password_reset(db_session, settings, owner_email, adapter)
    assert len(adapter.messages) == 1
    token = _token_from_message(adapter.messages[0])
    record = db_session.scalar(select(PasswordResetToken))
    assert record is not None
    assert record.token_hash != token
    assert token not in record.token_hash

    confirm_password_reset(db_session, token, "reset-owner-password-789")
    db_session.refresh(auth.session)
    db_session.refresh(record)
    db_session.refresh(owner)
    assert auth.session.revoked_at is not None
    assert record.status == "used"
    assert verify_password("reset-owner-password-789", owner.password_hash)
    with pytest.raises(PasswordResetTokenError):
        confirm_password_reset(db_session, token, "another-password-123")


def test_password_reset_request_does_not_disclose_unknown_email(
    settings, db_session: Session
) -> None:
    adapter = RecordingEmailAdapter()
    request_password_reset(db_session, settings, "unknown@example.com", adapter)
    assert adapter.messages == []
    assert db_session.scalar(select(PasswordResetToken)) is None


def test_persistent_account_lockout_and_user_facing_login_history(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    limited = settings.model_copy(
        update={"account_lockout_failure_threshold": 3, "account_lockout_minutes": 10}
    )
    request = request_for("/api/auth/login")

    for _ in range(3):
        assert (
            authenticate_account(
                db_session,
                limited,
                request,
                username=owner.username,
                password="wrong-password-123",
            )
            is None
        )
    db_session.refresh(owner)
    assert owner.failed_login_attempts == 3
    assert owner.locked_until is not None
    assert (
        authenticate_account(
            db_session,
            limited,
            request,
            username=owner.username,
            password="owner-password-123",
        )
        is not None
    )
    history = login_history(db_session, _auth_for(db_session, owner, "history"))
    assert [event.event_type for event in history.events[:3]] == [
        "locked",
        "failed",
        "failed",
    ]


def test_login_metadata_is_bounded_before_persistence(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "scheme": "http",
            "method": "POST",
            "path": "/api/auth/login",
            "raw_path": b"/api/auth/login",
            "query_string": b"",
            "headers": [(b"user-agent", b"x" * 2000)],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
    )
    assert (
        authenticate_account(
            db_session,
            settings,
            request,
            username=owner.username,
            password="wrong-password-123",
        )
        is None
    )
    db_session.refresh(owner)
    history = login_history(db_session, _auth_for(db_session, owner, "bounded-metadata"))
    assert owner.failed_login_attempts == 1
    assert history.events[0].user_agent == "x" * 512

    _token, auth_session = create_auth_session(
        db=db_session,
        settings=settings,
        user=owner,
        request=request,
    )
    assert auth_session.ip_address == "127.0.0.1"
    assert auth_session.user_agent == "x" * 512


def test_session_inventory_and_revocation_are_account_scoped(db_session: Session) -> None:
    owner = _owner(db_session)
    current = _auth_for(db_session, owner, "session-current")
    other = _auth_for(db_session, owner, "session-other")
    inventory = list_sessions(db_session, current)
    assert {session.id for session in inventory.sessions} == {current.session.id, other.session.id}
    assert [session.id for session in inventory.sessions if session.current] == [current.session.id]

    assert revoke_other_sessions(db_session, current) == 1
    db_session.refresh(other.session)
    assert other.session.revoked_at is not None
    assert revoke_session(db_session, current, current.session.id) is True
    with pytest.raises(SessionNotFoundError):
        revoke_session(db_session, current, current.session.id)


def test_invitation_lifecycle_supports_all_roles_and_technician_profile(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    owner_auth = _auth_for(db_session, owner, "invitations")
    accepted: dict[ShopRole, UserAccount] = {}

    for role in (ShopRole.OWNER, ShopRole.MANAGER, ShopRole.TECHNICIAN):
        adapter = RecordingEmailAdapter()
        invitation = create_invitation(
            db_session,
            settings,
            owner_auth,
            ShopInvitationCreate(email=f"{role.value}@example.com", role=role),
            adapter,
        )
        assert len(adapter.messages) == 1
        raw_token = _token_from_message(adapter.messages[0])
        stored = db_session.get(ShopInvitation, invitation.id)
        assert stored is not None
        assert stored.token_hash != raw_token
        user = accept_invitation(
            db_session,
            ShopInvitationAccept(
                token=raw_token,
                display_name=f"Invited {role.value.title()}",
                username=f"invited-{role.value}",
                password="invited-password-123",
            ),
        )
        accepted[role] = user
        membership = db_session.scalar(
            select(ShopMembership).where(ShopMembership.user_account_id == user.id)
        )
        assert membership is not None
        assert membership.role == role.value
        assert user.email_verified_at is not None

    technician = db_session.scalar(
        select(Technician).where(Technician.user_account_id == accepted[ShopRole.TECHNICIAN].id)
    )
    assert technician is not None
    members = list_members(db_session, owner_auth)
    assert {member.role for member in members} >= {
        ShopRole.OWNER,
        ShopRole.MANAGER,
        ShopRole.TECHNICIAN,
    }


def test_revoked_invitation_cannot_be_accepted(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    auth = _auth_for(db_session, owner, "revoke-invite")
    adapter = RecordingEmailAdapter()
    invitation = create_invitation(
        db_session,
        settings,
        auth,
        ShopInvitationCreate(email="revoked@example.com", role=ShopRole.MANAGER),
        adapter,
    )
    token = _token_from_message(adapter.messages[0])
    revoke_invitation(db_session, auth, invitation.id)
    with pytest.raises(InvitationError):
        accept_invitation(
            db_session,
            ShopInvitationAccept(
                token=token,
                display_name="Revoked Invite",
                username="revoked-invite",
                password="revoked-password-123",
            ),
        )
    assert list_invitations(db_session, auth)[0].revoked_at is not None


def test_invitation_constraint_race_is_converted_to_domain_conflict(
    settings,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _owner(db_session)
    auth = _auth_for(db_session, owner, "invitation-race")

    def fail_flush(*_args, **_kwargs) -> None:
        raise IntegrityError("duplicate pending invitation", {}, Exception("constraint"))

    monkeypatch.setattr(account_security_store.Session, "flush", fail_flush)
    with pytest.raises(InvitationConflictError):
        create_invitation(
            db_session,
            settings,
            auth,
            ShopInvitationCreate(email="race@example.com", role=ShopRole.TECHNICIAN),
            RecordingEmailAdapter(),
        )
    assert db_session.in_transaction() is False


def test_technician_invitation_links_existing_unlinked_profile(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    auth = _auth_for(db_session, owner, "existing-profile")
    membership = db_session.scalar(
        select(ShopMembership).where(ShopMembership.user_account_id == owner.id)
    )
    assert membership is not None
    profile = Technician(
        owner_user_id=owner.id,
        shop_id=membership.shop_id,
        first_name="Existing",
        last_name="Technician",
        email="existing-tech@example.com",
        email_normalized="existing-tech@example.com",
    )
    db_session.add(profile)
    db_session.commit()
    profile_id = profile.id
    adapter = RecordingEmailAdapter()
    create_invitation(
        db_session,
        settings,
        auth,
        ShopInvitationCreate(email="existing-tech@example.com", role=ShopRole.TECHNICIAN),
        adapter,
    )
    user = accept_invitation(
        db_session,
        ShopInvitationAccept(
            token=_token_from_message(adapter.messages[0]),
            display_name="Existing Technician",
            username="existing-technician",
            password="existing-tech-password-123",
        ),
    )
    profiles = db_session.scalars(
        select(Technician).where(Technician.email_normalized == "existing-tech@example.com")
    ).all()
    assert [item.id for item in profiles] == [profile_id]
    assert profiles[0].user_account_id == user.id


def test_manager_invitation_permissions_and_cross_shop_member_isolation(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    owner_auth = _auth_for(db_session, owner, "manager-permissions")
    adapter = RecordingEmailAdapter()
    create_invitation(
        db_session,
        settings,
        owner_auth,
        ShopInvitationCreate(email="permission-manager@example.com", role=ShopRole.MANAGER),
        adapter,
    )
    manager = accept_invitation(
        db_session,
        ShopInvitationAccept(
            token=_token_from_message(adapter.messages[0]),
            display_name="Permission Manager",
            username="permission-manager",
            password="permission-password-123",
        ),
    )
    manager_auth = _auth_for(db_session, manager, "manager-auth")
    with pytest.raises(InvitationError):
        create_invitation(
            db_session,
            settings,
            manager_auth,
            ShopInvitationCreate(email="owner-by-manager@example.com", role=ShopRole.OWNER),
            RecordingEmailAdapter(),
        )
    with pytest.raises(InvitationError):
        create_invitation(
            db_session,
            settings,
            manager_auth,
            ShopInvitationCreate(email="manager-by-manager@example.com", role=ShopRole.MANAGER),
            RecordingEmailAdapter(),
        )
    technician_adapter = RecordingEmailAdapter()
    technician_invite = create_invitation(
        db_session,
        settings,
        manager_auth,
        ShopInvitationCreate(email="tech-by-manager@example.com", role=ShopRole.TECHNICIAN),
        technician_adapter,
    )
    assert technician_invite.role == ShopRole.TECHNICIAN

    manager_membership = db_session.scalar(
        select(ShopMembership).where(ShopMembership.user_account_id == manager.id)
    )
    assert manager_membership is not None
    legacy_token = "legacy-manager-privileged-invitation"
    db_session.add(
        ShopInvitation(
            shop_id=manager_membership.shop_id,
            email="legacy-owner-by-manager@example.com",
            email_normalized="legacy-owner-by-manager@example.com",
            role="owner",
            invited_by_user_account_id=manager.id,
            token_hash=account_security_store._token_hash(legacy_token),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db_session.commit()
    with pytest.raises(InvitationError):
        accept_invitation(
            db_session,
            ShopInvitationAccept(
                token=legacy_token,
                display_name="Legacy Privileged Invite",
                username="legacy-privileged-invite",
                password="legacy-privileged-password-123",
            ),
        )
    assert (
        db_session.scalar(
            select(UserAccount.id).where(UserAccount.username == "legacy-privileged-invite")
        )
        is None
    )

    update_member_status(
        db_session,
        owner_auth,
        manager.id,
        AccountStatusUpdate(status="suspended"),
    )
    stored_invite = db_session.get(ShopInvitation, technician_invite.id)
    assert stored_invite is not None
    assert stored_invite.revoked_at is not None
    with pytest.raises(InvitationError):
        accept_invitation(
            db_session,
            ShopInvitationAccept(
                token=_token_from_message(technician_adapter.messages[0]),
                display_name="Planted Technician",
                username="planted-technician",
                password="planted-password-123",
            ),
        )

    other_owner = create_user(
        db_session,
        username="other-account-admin",
        password="other-account-password-123",
        settings=settings,
    )
    other_auth = _auth_for(db_session, other_owner, "other-shop")
    with pytest.raises(MemberManagementError):
        update_member_status(
            db_session,
            other_auth,
            manager.id,
            AccountStatusUpdate(status="suspended"),
        )


def test_suspension_revokes_membership_sessions_and_reactivation_restores_login(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    owner_auth = _auth_for(db_session, owner, "member-status")
    adapter = RecordingEmailAdapter()
    create_invitation(
        db_session,
        settings,
        owner_auth,
        ShopInvitationCreate(email="status-tech@example.com", role=ShopRole.TECHNICIAN),
        adapter,
    )
    technician_user = accept_invitation(
        db_session,
        ShopInvitationAccept(
            token=_token_from_message(adapter.messages[0]),
            display_name="Status Tech",
            username="status-tech",
            password="status-password-123",
        ),
    )
    technician_auth = _auth_for(db_session, technician_user, "status-session")
    reset_record = PasswordResetToken(
        user_account_id=technician_user.id,
        token_hash="b" * 64,
        status="active",
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db_session.add(reset_record)
    db_session.commit()

    suspended = update_member_status(
        db_session,
        owner_auth,
        technician_user.id,
        AccountStatusUpdate(status="suspended"),
    )
    db_session.refresh(technician_auth.session)
    assert suspended.account_status == "suspended"
    assert suspended.membership_active is False
    assert technician_auth.session.revoked_at is not None
    db_session.refresh(reset_record)
    assert reset_record.status == "revoked"
    assert (
        authenticate_account(
            db_session,
            settings,
            request_for("/api/auth/login"),
            username="status-tech",
            password="status-password-123",
        )
        is None
    )

    active = update_member_status(
        db_session,
        owner_auth,
        technician_user.id,
        AccountStatusUpdate(status="active"),
    )
    assert active.membership_active is True
    assert (
        authenticate_account(
            db_session,
            settings,
            request_for("/api/auth/login"),
            username="status-tech",
            password="status-password-123",
        )
        is not None
    )


def test_mfa_architecture_reports_factor_metadata_without_secrets(db_session: Session) -> None:
    owner = _owner(db_session)
    auth = _auth_for(db_session, owner, "mfa")
    db_session.add(
        AuthMfaFactor(
            user_account_id=owner.id,
            factor_type="external",
            status="active",
            label="Future identity provider",
            external_credential_id="provider-reference-only",
            verified_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    summary = security_summary(db_session, auth)
    assert summary.mfa_architecture_ready is True
    assert summary.active_mfa_factor_count == 1
    assert "secret" not in AuthMfaFactor.__table__.columns


def test_account_lifecycle_http_routes(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _owner(db_session)
    owner.email = "http-owner@example.com"
    owner.email_normalized = "http-owner@example.com"
    owner.email_verified_at = datetime.now(UTC)
    db_session.add(owner)
    db_session.commit()
    adapter = RecordingEmailAdapter()
    reset_limiter = SlidingWindowRateLimiter(limit=1, window_seconds=3600)
    invitation_limiter = SlidingWindowRateLimiter(limit=1, window_seconds=3600)
    monkeypatch.setattr(main, "email_adapter", lambda: adapter)
    monkeypatch.setattr(
        main,
        "get_password_reset_rate_limiter",
        lambda _settings: reset_limiter,
    )
    monkeypatch.setattr(
        main,
        "get_invitation_acceptance_rate_limiter",
        lambda _settings: invitation_limiter,
    )
    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        login = client.post(
            "/api/auth/login",
            json={"username": owner.username, "password": "owner-password-123"},
        )
        assert login.status_code == 200
        assert client.get("/api/auth/security").status_code == 200
        assert client.get("/api/auth/sessions").json()["sessions"][0]["current"] is True
        assert (
            client.get("/api/auth/login-history").json()["events"][0]["event_type"] == "succeeded"
        )

        invitation = client.post(
            "/api/shop/invitations",
            json={"email": "http-manager@example.com", "role": "manager"},
        )
        assert invitation.status_code == 200
        invitation_token = _token_from_message(adapter.messages[-1])
        accepted = TestClient(main.app).post(
            "/api/invitations/accept",
            json={
                "token": invitation_token,
                "display_name": "HTTP Manager",
                "username": "http-manager",
                "password": "http-manager-password-123",
            },
        )
        assert accepted.status_code == 200
        manager_id = accepted.json()["user"]["id"]
        assert (
            client.patch(
                f"/api/shop/members/{manager_id}/status", json={"status": "suspended"}
            ).status_code
            == 200
        )
        blocked = TestClient(main.app).post(
            "/api/auth/login",
            json={"username": "http-manager", "password": "http-manager-password-123"},
        )
        assert blocked.status_code == 401

        reset_request = client.post("/api/auth/password/reset-request", json={"email": owner.email})
        assert reset_request.status_code == 200
        reset_token = _token_from_message(adapter.messages[-1])
        reset = client.post(
            "/api/auth/password/reset-confirm",
            json={"token": reset_token, "new_password": "http-reset-password-123"},
        )
        assert reset.status_code == 200
        assert client.get("/api/auth/me").status_code == 401
        relogin = client.post(
            "/api/auth/login",
            json={"username": owner.username, "password": "http-reset-password-123"},
        )
        assert relogin.status_code == 200
    finally:
        main.app.dependency_overrides.clear()
