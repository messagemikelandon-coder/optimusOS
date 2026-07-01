from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import build_session_factory, get_db_session
from app.db_models import AuthSession, UserAccount

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[Session, Depends(get_db_session)]

_password_hasher = PasswordHasher()


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: UserAccount
    session: AuthSession


def normalize_username(value: str) -> str:
    return value.strip().casefold()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def maybe_rehash_password(password: str, user: UserAccount, db: Session) -> None:
    if not _password_hasher.check_needs_rehash(user.password_hash):
        return
    user.password_hash = hash_password(password)
    db.add(user)
    db.commit()


def session_expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _owner_exists_query() -> Select[tuple[int]]:
    return select(func.count()).select_from(UserAccount).where(UserAccount.role == "owner")


def bootstrap_owner_account(settings: Settings | None = None, db: Session | None = None) -> int:
    resolved_settings = settings or get_settings()
    managed_session = db is None
    session = db or build_session_factory(resolved_settings.database_url)()
    try:
        owner_count = session.scalar(_owner_exists_query()) or 0
        if owner_count > 0:
            print("Owner account already present.")
            return 0

        if (
            not resolved_settings.optimus_owner_username
            or not resolved_settings.optimus_owner_password
        ):
            print(
                "Owner bootstrap skipped: OPTIMUS_OWNER_USERNAME or OPTIMUS_OWNER_PASSWORD missing."
            )
            return 1

        owner = UserAccount(
            username=normalize_username(resolved_settings.optimus_owner_username),
            display_name="Owner",
            role="owner",
            password_hash=hash_password(resolved_settings.optimus_owner_password),
            is_active=True,
        )
        session.add(owner)
        session.commit()
        print("Owner account created.")
        return 0
    finally:
        if managed_session:
            session.close()


def create_auth_session(
    *,
    db: Session,
    settings: Settings,
    user: UserAccount,
    request: Request,
) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(48)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=session_expiry(settings),
        last_seen_at=datetime.now(UTC),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    user.last_login_at = datetime.now(UTC)
    db.add(user)
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    auth_session.expires_at = ensure_utc(auth_session.expires_at)
    return token, auth_session


def set_session_cookie(
    response: Response, settings: Settings, token: str, expires_at: datetime
) -> None:
    secure = settings.frontend_origin.lower().startswith("https://")
    normalized_expiry = ensure_utc(expires_at)
    max_age = max(int((normalized_expiry - datetime.now(UTC)).total_seconds()), 0)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=max_age,
        expires=normalized_expiry,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.frontend_origin.lower().startswith("https://"),
        samesite="lax",
        path="/",
    )


def authenticate_user(
    *,
    db: Session,
    username: str,
    password: str,
) -> UserAccount | None:
    user = db.scalar(
        select(UserAccount).where(UserAccount.username == normalize_username(username))
    )
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    maybe_rehash_password(password, user, db)
    return user


def _active_session_query(token_hash: str) -> Select[tuple[AuthSession]]:
    return (
        select(AuthSession)
        .where(AuthSession.token_hash == token_hash)
        .where(AuthSession.revoked_at.is_(None))
        .where(AuthSession.expires_at > datetime.now(UTC))
    )


def get_current_auth_context(
    request: Request,
    db: DbSessionDep,
    settings: SettingsDep,
) -> AuthContext:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    auth_session = db.scalar(_active_session_query(hash_session_token(token)))
    if auth_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    user = db.get(UserAccount, auth_session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required."
        )

    auth_session.last_seen_at = datetime.now(UTC)
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    auth_session.expires_at = ensure_utc(auth_session.expires_at)
    return AuthContext(user=user, session=auth_session)


def require_authenticated_user(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
) -> UserAccount:
    return auth.user
