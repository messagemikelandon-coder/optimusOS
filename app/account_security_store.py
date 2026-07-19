from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    AuthContext,
    effective_shop_id,
    ensure_utc,
    hash_password,
    maybe_rehash_password,
    normalize_username,
    request_metadata,
    verify_password,
)
from app.config import Settings
from app.db_models import (
    AuthLoginEvent,
    AuthMfaFactor,
    AuthSession,
    PasswordResetToken,
    ShopEvent,
    ShopInvitation,
    ShopMembership,
    Technician,
    UserAccount,
)
from app.models import (
    AccountSecurityRead,
    AccountStatusUpdate,
    AuthLoginEventRead,
    AuthLoginHistoryResponse,
    AuthSessionListResponse,
    AuthSessionRead,
    PasswordChangeRequest,
    ShopInvitationAccept,
    ShopInvitationCreate,
    ShopInvitationRead,
    ShopMemberRead,
    ShopRole,
)
from app.services.email import EmailAdapter, EmailMessage
from app.technician_store import TechnicianConflictError, enforce_technician_seat_limit

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_GENERIC_RESET_ERROR = "This password-reset code is invalid or has expired."
_GENERIC_INVITATION_ERROR = "This invitation is invalid, expired, or unavailable."


class AccountSecurityError(Exception):
    pass


class PasswordChangeError(AccountSecurityError):
    pass


class PasswordResetTokenError(AccountSecurityError):
    pass


class SessionNotFoundError(AccountSecurityError):
    pass


class InvitationError(AccountSecurityError):
    pass


class InvitationConflictError(InvitationError):
    pass


class MemberManagementError(AccountSecurityError):
    pass


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if not _EMAIL_RE.fullmatch(normalized):
        raise InvitationError("Email address is invalid.")
    return normalized


def _add_login_event(
    db: Session,
    user: UserAccount,
    event_type: str,
    request: Request,
    *,
    auth_session_id: int | None = None,
) -> None:
    ip_address, user_agent = request_metadata(request)
    db.add(
        AuthLoginEvent(
            user_account_id=user.id,
            auth_session_id=auth_session_id,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )


def authenticate_account(
    db: Session,
    settings: Settings,
    request: Request,
    *,
    username: str,
    password: str,
) -> UserAccount | None:
    """Authenticate while enforcing persistent per-account lockout.

    Every externally visible failure remains the same generic 401 in the
    route. Known-account failures are recorded for that account's own login
    history; unknown usernames are never persisted.
    """
    user = db.scalar(
        select(UserAccount)
        .where(UserAccount.username == normalize_username(username))
        .with_for_update()
    )
    if user is None:
        return None

    now = datetime.now(UTC)
    if not user.is_active or user.account_status != "active":
        _add_login_event(db, user, "blocked", request)
        db.commit()
        return None
    password_valid = verify_password(password, user.password_hash)
    if user.locked_until is not None and ensure_utc(user.locked_until) > now:
        if not password_valid:
            _add_login_event(db, user, "locked", request)
            db.commit()
            return None
        # A correct credential clears the defensive cooldown. This preserves
        # persistent brute-force throttling without letting an attacker deny
        # service to a known username with a handful of bad guesses.
        user.locked_until = None
        user.failed_login_attempts = 0
    if user.locked_until is not None:
        user.locked_until = None
        user.failed_login_attempts = 0

    if not password_valid:
        user.failed_login_attempts += 1
        user.last_failed_login_at = now
        event_type = "failed"
        if user.failed_login_attempts >= settings.account_lockout_failure_threshold:
            user.locked_until = now + timedelta(minutes=settings.account_lockout_minutes)
            event_type = "locked"
        db.add(user)
        _add_login_event(db, user, event_type, request)
        db.commit()
        return None

    user.failed_login_attempts = 0
    user.last_failed_login_at = None
    user.locked_until = None
    db.add(user)
    db.commit()
    maybe_rehash_password(password, user, db)
    db.refresh(user)
    return user


def record_login_success(
    db: Session, user: UserAccount, auth_session: AuthSession, request: Request
) -> None:
    _add_login_event(db, user, "succeeded", request, auth_session_id=auth_session.id)
    db.commit()


def change_password(db: Session, auth: AuthContext, payload: PasswordChangeRequest) -> None:
    user = db.scalar(select(UserAccount).where(UserAccount.id == auth.user.id).with_for_update())
    if user is None or not verify_password(payload.current_password, user.password_hash):
        raise PasswordChangeError("Current password is incorrect.")
    if verify_password(payload.new_password, user.password_hash):
        raise PasswordChangeError("New password must be different from the current password.")
    user.password_hash = hash_password(payload.new_password)
    user.failed_login_attempts = 0
    user.last_failed_login_at = None
    user.locked_until = None
    now = datetime.now(UTC)
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.id != auth.session.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_account_id == user.id,
            PasswordResetToken.status == "active",
        )
        .values(status="revoked", revoked_at=now)
    )
    db.add(user)
    db.commit()


def request_password_reset(
    db: Session,
    settings: Settings,
    email: str,
    email_adapter: EmailAdapter,
) -> None:
    normalized = email.strip().lower()
    token = secrets.token_urlsafe(32)
    user = db.scalar(
        select(UserAccount).where(UserAccount.email_normalized == normalized).with_for_update()
    )
    if (
        user is None
        or not user.is_active
        or user.account_status != "active"
        or user.email_verified_at is None
        or not user.email
    ):
        return

    now = datetime.now(UTC)
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_account_id == user.id,
            PasswordResetToken.status == "active",
        )
        .values(status="revoked", revoked_at=now)
    )
    db.add(
        PasswordResetToken(
            user_account_id=user.id,
            token_hash=_token_hash(token),
            status="active",
            expires_at=now + timedelta(minutes=settings.password_reset_token_ttl_minutes),
        )
    )
    db.commit()
    email_adapter.send(
        EmailMessage(
            to=user.email,
            subject="Reset your OptimusOS password",
            body=(
                f"Hi {user.display_name},\n\n"
                "Use this one-time code to reset your OptimusOS password:\n\n"
                f"{token}\n\n"
                f"This code expires in {settings.password_reset_token_ttl_minutes} minute(s). "
                "If you didn't request this, you can ignore it."
            ),
        )
    )


def confirm_password_reset(db: Session, token: str, new_password: str) -> None:
    token_hash = _token_hash(token)
    candidate = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    if candidate is None:
        raise PasswordResetTokenError(_GENERIC_RESET_ERROR)
    # Every reset mutation locks UserAccount first and token second. Request,
    # confirmation, password change, and suspension now share this ordering.
    user = db.scalar(
        select(UserAccount).where(UserAccount.id == candidate.user_account_id).with_for_update()
    )
    record = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.id == candidate.id).with_for_update()
    )
    if record is None or record.status != "active":
        raise PasswordResetTokenError(_GENERIC_RESET_ERROR)
    now = datetime.now(UTC)
    if ensure_utc(record.expires_at) <= now:
        record.status = "expired"
        db.add(record)
        db.commit()
        raise PasswordResetTokenError(_GENERIC_RESET_ERROR)
    if user is None or not user.is_active or user.account_status != "active":
        raise PasswordResetTokenError(_GENERIC_RESET_ERROR)

    user.password_hash = hash_password(new_password)
    user.failed_login_attempts = 0
    user.last_failed_login_at = None
    user.locked_until = None
    record.status = "used"
    record.used_at = now
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.add(user)
    db.add(record)
    db.commit()


def list_sessions(db: Session, auth: AuthContext) -> AuthSessionListResponse:
    now = datetime.now(UTC)
    sessions = db.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == auth.user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .order_by(AuthSession.last_seen_at.desc(), AuthSession.created_at.desc())
    ).all()
    return AuthSessionListResponse(
        sessions=[
            AuthSessionRead(
                id=session.id,
                current=session.id == auth.session.id,
                created_at=ensure_utc(session.created_at),
                last_seen_at=ensure_utc(session.last_seen_at) if session.last_seen_at else None,
                expires_at=ensure_utc(session.expires_at),
                ip_address=session.ip_address,
                user_agent=session.user_agent,
            )
            for session in sessions
        ]
    )


def revoke_session(db: Session, auth: AuthContext, session_id: int) -> bool:
    session = db.scalar(
        select(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.user_id == auth.user.id)
        .with_for_update()
    )
    if session is None or session.revoked_at is not None:
        raise SessionNotFoundError("Session not found.")
    session.revoked_at = datetime.now(UTC)
    db.add(session)
    db.commit()
    return session.id == auth.session.id


def revoke_other_sessions(db: Session, auth: AuthContext) -> int:
    session_ids = db.scalars(
        select(AuthSession.id).where(
            AuthSession.user_id == auth.user.id,
            AuthSession.id != auth.session.id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == auth.user.id,
            AuthSession.id != auth.session.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()
    return len(session_ids)


def login_history(db: Session, auth: AuthContext) -> AuthLoginHistoryResponse:
    events = db.scalars(
        select(AuthLoginEvent)
        .where(AuthLoginEvent.user_account_id == auth.user.id)
        .order_by(AuthLoginEvent.created_at.desc(), AuthLoginEvent.id.desc())
        .limit(50)
    ).all()
    return AuthLoginHistoryResponse(
        events=[
            AuthLoginEventRead(
                id=event.id,
                event_type=cast(
                    Literal["succeeded", "failed", "locked", "blocked"], event.event_type
                ),
                ip_address=event.ip_address,
                user_agent=event.user_agent,
                created_at=ensure_utc(event.created_at),
            )
            for event in events
        ]
    )


def security_summary(db: Session, auth: AuthContext) -> AccountSecurityRead:
    factor_count = db.scalar(
        select(func.count())
        .select_from(AuthMfaFactor)
        .where(AuthMfaFactor.user_account_id == auth.user.id, AuthMfaFactor.status == "active")
    )
    return AccountSecurityRead(
        account_status=cast(Literal["active", "disabled", "suspended"], auth.user.account_status),
        locked_until=ensure_utc(auth.user.locked_until) if auth.user.locked_until else None,
        active_mfa_factor_count=factor_count or 0,
    )


def _invitation_to_read(invitation: ShopInvitation) -> ShopInvitationRead:
    return ShopInvitationRead(
        id=invitation.id,
        shop_id=invitation.shop_id,
        email=invitation.email,
        role=ShopRole(invitation.role),
        invited_by_user_account_id=invitation.invited_by_user_account_id,
        expires_at=ensure_utc(invitation.expires_at),
        accepted_at=ensure_utc(invitation.accepted_at) if invitation.accepted_at else None,
        revoked_at=ensure_utc(invitation.revoked_at) if invitation.revoked_at else None,
        created_at=ensure_utc(invitation.created_at),
    )


def create_invitation(
    db: Session,
    settings: Settings,
    auth: AuthContext,
    payload: ShopInvitationCreate,
    email_adapter: EmailAdapter,
) -> ShopInvitationRead:
    if auth.user.role == "manager" and payload.role.value != "technician":
        raise InvitationError("Managers can invite technicians only.")
    shop_id = effective_shop_id(db, auth)
    email_normalized = _normalize_email(payload.email)
    if db.scalar(select(UserAccount.id).where(UserAccount.email_normalized == email_normalized)):
        raise InvitationConflictError("Unable to prepare an invitation for these details.")

    now = datetime.now(UTC)
    db.execute(
        update(ShopInvitation)
        .where(
            ShopInvitation.shop_id == shop_id,
            ShopInvitation.email_normalized == email_normalized,
            ShopInvitation.accepted_at.is_(None),
            ShopInvitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = secrets.token_urlsafe(32)
    invitation = ShopInvitation(
        shop_id=shop_id,
        email=payload.email.strip(),
        email_normalized=email_normalized,
        role=payload.role.value,
        invited_by_user_account_id=auth.user.id,
        token_hash=_token_hash(token),
        expires_at=now + timedelta(hours=settings.shop_invitation_token_ttl_hours),
    )
    try:
        db.add(invitation)
        db.flush()
        db.add(
            ShopEvent(
                shop_id=shop_id,
                event_type="shop_invitation_created",
                actor_user_account_id=auth.user.id,
                actor_name=auth.user.display_name,
                event_metadata={"invitation_id": invitation.id, "role": payload.role.value},
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise InvitationConflictError(
            "Unable to prepare an invitation for these details."
        ) from None
    db.refresh(invitation)
    email_adapter.send(
        EmailMessage(
            to=invitation.email,
            subject="You are invited to OptimusOS",
            body=(
                "Use this one-time invitation code to join the Shop:\n\n"
                f"{token}\n\n"
                f"This code expires in {settings.shop_invitation_token_ttl_hours} hour(s)."
            ),
        )
    )
    return _invitation_to_read(invitation)


def list_invitations(db: Session, auth: AuthContext) -> list[ShopInvitationRead]:
    invitations = db.scalars(
        select(ShopInvitation)
        .where(ShopInvitation.shop_id == effective_shop_id(db, auth))
        .order_by(ShopInvitation.created_at.desc(), ShopInvitation.id.desc())
        .limit(100)
    ).all()
    return [_invitation_to_read(invitation) for invitation in invitations]


def revoke_invitation(db: Session, auth: AuthContext, invitation_id: int) -> None:
    invitation = db.scalar(
        select(ShopInvitation)
        .where(
            ShopInvitation.id == invitation_id,
            ShopInvitation.shop_id == effective_shop_id(db, auth),
        )
        .with_for_update()
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
    ):
        raise InvitationError("Invitation not found or no longer active.")
    if auth.user.role == "manager" and invitation.role != "technician":
        raise InvitationError("Managers can revoke technician invitations only.")
    invitation.revoked_at = datetime.now(UTC)
    db.add(invitation)
    db.add(
        ShopEvent(
            shop_id=invitation.shop_id,
            event_type="shop_invitation_revoked",
            actor_user_account_id=auth.user.id,
            actor_name=auth.user.display_name,
            event_metadata={"invitation_id": invitation.id},
        )
    )
    db.commit()


def accept_invitation(db: Session, payload: ShopInvitationAccept) -> UserAccount:
    invitation = db.scalar(
        select(ShopInvitation)
        .where(ShopInvitation.token_hash == _token_hash(payload.token))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or ensure_utc(invitation.expires_at) <= now
    ):
        if (
            invitation is not None
            and invitation.accepted_at is None
            and invitation.revoked_at is None
        ):
            invitation.revoked_at = now
            db.add(invitation)
            db.commit()
        raise InvitationError(_GENERIC_INVITATION_ERROR)

    inviter_role = db.scalar(
        select(ShopMembership.role)
        .join(UserAccount, UserAccount.id == ShopMembership.user_account_id)
        .where(
            ShopMembership.shop_id == invitation.shop_id,
            ShopMembership.user_account_id == invitation.invited_by_user_account_id,
            ShopMembership.role.in_(("owner", "manager")),
            ShopMembership.is_active.is_(True),
            UserAccount.is_active.is_(True),
            UserAccount.account_status == "active",
        )
    )
    if inviter_role is None or (inviter_role == "manager" and invitation.role != "technician"):
        raise InvitationError(_GENERIC_INVITATION_ERROR)

    username = normalize_username(payload.username)
    if db.scalar(select(UserAccount.id).where(UserAccount.username == username)) or db.scalar(
        select(UserAccount.id).where(UserAccount.email_normalized == invitation.email_normalized)
    ):
        raise InvitationConflictError(_GENERIC_INVITATION_ERROR)
    owner_id = db.scalar(
        select(ShopMembership.user_account_id)
        .join(UserAccount, UserAccount.id == ShopMembership.user_account_id)
        .where(
            ShopMembership.shop_id == invitation.shop_id,
            ShopMembership.role == "owner",
            ShopMembership.is_active.is_(True),
            UserAccount.role == "owner",
            UserAccount.is_active.is_(True),
            UserAccount.account_status == "active",
        )
        .order_by(ShopMembership.id)
        .limit(1)
    )
    if owner_id is None:
        raise InvitationError(_GENERIC_INVITATION_ERROR)

    user = UserAccount(
        username=username,
        display_name=payload.display_name,
        role=invitation.role,
        shop_owner_id=owner_id if invitation.role != "owner" else None,
        password_hash=hash_password(payload.password),
        email=invitation.email,
        email_normalized=invitation.email_normalized,
        email_verified_at=now,
        account_status="active",
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
        db.add(
            ShopMembership(
                shop_id=invitation.shop_id,
                user_account_id=user.id,
                role=invitation.role,
            )
        )
        if invitation.role == "technician":
            name_parts = payload.display_name.strip().split(maxsplit=1)
            existing_profiles = db.scalars(
                select(Technician)
                .where(
                    Technician.shop_id == invitation.shop_id,
                    Technician.email_normalized == invitation.email_normalized,
                    Technician.is_archived.is_(False),
                )
                .order_by(Technician.id)
                .limit(2)
                .with_for_update()
            ).all()
            if len(existing_profiles) > 1 or (
                existing_profiles and existing_profiles[0].user_account_id is not None
            ):
                db.rollback()
                raise InvitationConflictError(_GENERIC_INVITATION_ERROR)
            if existing_profiles:
                profile = existing_profiles[0]
                profile.user_account_id = user.id
                db.add(profile)
            else:
                # /goal Phase 7 security-review finding: this is the other
                # code path (besides technician_store.create_technician)
                # that can create a brand-new Technician row -- it must be
                # seat-limit-gated too, or invitations silently bypass the
                # subscription's paid seat count entirely.
                try:
                    enforce_technician_seat_limit(db, invitation.shop_id)
                except TechnicianConflictError:
                    db.rollback()
                    raise InvitationConflictError(_GENERIC_INVITATION_ERROR) from None
                db.add(
                    Technician(
                        owner_user_id=owner_id,
                        shop_id=invitation.shop_id,
                        user_account_id=user.id,
                        first_name=name_parts[0],
                        last_name=name_parts[1] if len(name_parts) > 1 else None,
                        email=invitation.email,
                        email_normalized=invitation.email_normalized,
                    )
                )
        invitation.accepted_at = now
        db.add(invitation)
        db.add(
            ShopEvent(
                shop_id=invitation.shop_id,
                event_type="shop_invitation_accepted",
                actor_user_account_id=user.id,
                actor_name=user.display_name,
                event_metadata={"invitation_id": invitation.id, "role": invitation.role},
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise InvitationConflictError(_GENERIC_INVITATION_ERROR) from None
    db.refresh(user)
    return user


def list_members(db: Session, auth: AuthContext) -> list[ShopMemberRead]:
    rows = db.execute(
        select(ShopMembership, UserAccount)
        .join(UserAccount, UserAccount.id == ShopMembership.user_account_id)
        .where(ShopMembership.shop_id == effective_shop_id(db, auth))
        .order_by(ShopMembership.id)
    ).all()
    return [
        ShopMemberRead(
            user_account_id=user.id,
            display_name=user.display_name,
            username=user.username,
            email=user.email,
            role=ShopRole(membership.role),
            account_status=cast(Literal["active", "disabled", "suspended"], user.account_status),
            membership_active=membership.is_active,
        )
        for membership, user in rows
    ]


def update_member_status(
    db: Session,
    auth: AuthContext,
    user_account_id: int,
    payload: AccountStatusUpdate,
) -> ShopMemberRead:
    shop_id = effective_shop_id(db, auth)
    row = db.execute(
        select(ShopMembership, UserAccount)
        .join(UserAccount, UserAccount.id == ShopMembership.user_account_id)
        .where(
            ShopMembership.shop_id == shop_id,
            ShopMembership.user_account_id == user_account_id,
        )
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise MemberManagementError("Shop member not found.")
    membership, user = row
    if user.id == auth.user.id:
        raise MemberManagementError("Use another administrator to change your account status.")
    if user.role == "owner":
        raise MemberManagementError("Owner offboarding requires a separate ownership transfer.")
    if auth.user.role == "manager" and user.role != "technician":
        raise MemberManagementError("Managers can change technician status only.")

    active = payload.status == "active"
    if active and user.role == "technician":
        technician = db.scalar(
            select(Technician).where(
                Technician.shop_id == shop_id,
                Technician.user_account_id == user.id,
            )
        )
        if technician is None or technician.is_archived:
            raise MemberManagementError(
                "Archived technician profiles must be restored before account reactivation."
            )
    user.account_status = payload.status
    user.is_active = active
    membership.is_active = active
    if not active:
        now = datetime.now(UTC)
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_account_id == user.id,
                PasswordResetToken.status == "active",
            )
            .values(status="revoked", revoked_at=now)
        )
        db.execute(
            update(ShopInvitation)
            .where(
                ShopInvitation.shop_id == shop_id,
                ShopInvitation.invited_by_user_account_id == user.id,
                ShopInvitation.accepted_at.is_(None),
                ShopInvitation.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
    db.add(user)
    db.add(membership)
    db.add(
        ShopEvent(
            shop_id=shop_id,
            event_type="shop_member_status_changed",
            actor_user_account_id=auth.user.id,
            actor_name=auth.user.display_name,
            event_metadata={"user_account_id": user.id, "status": payload.status},
        )
    )
    db.commit()
    return ShopMemberRead(
        user_account_id=user.id,
        display_name=user.display_name,
        username=user.username,
        email=user.email,
        role=ShopRole(membership.role),
        account_status=cast(Literal["active", "disabled", "suspended"], user.account_status),
        membership_active=membership.is_active,
    )
