from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import build_session_factory, get_db_session
from app.db_models import AuthSession, ShopMembership, UserAccount

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[Session, Depends(get_db_session)]

_password_hasher = PasswordHasher()
logger = logging.getLogger("optimus")


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
        session.flush()

        # Deferred import: app.shop_store imports AuthContext/effective_owner_id
        # from this module, so importing it at module load time would be a
        # circular import. A fresh install runs migrations before any owner
        # exists, so the migration's own Shop backfill never covers this
        # owner -- this is the only code path that creates their Shop.
        from app.shop_store import create_shop_for_new_owner

        create_shop_for_new_owner(session, resolved_settings, owner)
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
    ip_address, user_agent = request_metadata(request)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=session_expiry(settings),
        last_seen_at=datetime.now(UTC),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    # Do not mint even a dormant session for an orphaned, deactivated, or
    # role-mismatched membership. Reactivation must require a fresh login.
    effective_shop_id(db, AuthContext(user=user, session=auth_session))
    user.last_login_at = datetime.now(UTC)
    db.add(user)
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    auth_session.expires_at = ensure_utc(auth_session.expires_at)
    return token, auth_session


def request_metadata(request: Request) -> tuple[str | None, str | None]:
    """Return request metadata bounded to the shared authentication schema."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return (
        ip_address[:64] if ip_address else None,
        user_agent[:512] if user_agent else None,
    )


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
    if user is None or not user.is_active or user.account_status != "active":
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
    try:
        auth_session = db.scalar(_active_session_query(hash_session_token(token)))
        if auth_session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )

        user = db.get(UserAccount, auth_session.user_id)
        if user is None or not user.is_active or user.account_status != "active":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )

        auth_session.last_seen_at = datetime.now(UTC)
        db.add(auth_session)
        db.commit()
        db.refresh(auth_session)
        auth_session.expires_at = ensure_utc(auth_session.expires_at)
        auth = AuthContext(user=user, session=auth_session)
        # Validate membership on every authenticated request, including routes
        # that do not happen to load a business record. This makes membership
        # deactivation immediate and prevents an orphaned or role-mismatched
        # session from reaching chat, location, context, or account surfaces.
        effective_shop_id(db, auth)
        return auth
    except SQLAlchemyError as exc:
        logger.warning("Authentication lookup failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication storage is unavailable.",
        ) from exc


def require_authenticated_user(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
) -> UserAccount:
    require_verified_email_if_present(auth)
    return auth.user


def effective_owner_id(auth: AuthContext) -> int:
    """The shop-owning user id that business data should be scoped to.

    This remains only as a compatibility value for legacy `owner_user_id`
    columns and human-readable record numbering. Authorization and record
    lookup must use `effective_shop_id()` and the real `shop_id` boundary.
    """
    if auth.user.role == "owner":
        return auth.user.id
    if auth.user.shop_owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not associated with a shop owner.",
        )
    return auth.user.shop_owner_id


def effective_shop_id(db: Session, auth: AuthContext) -> int:
    """Resolve the one active Shop membership for this account.

    Membership is the authorization source of truth. The legacy
    `UserAccount.shop_owner_id` pointer is deliberately ignored here so a
    stale or corrupted compatibility pointer cannot grant cross-shop access.
    Migration 028 enforces at most one active membership per user; the
    explicit two-row check keeps the application fail-closed on databases
    that have not applied that constraint yet.
    """
    memberships = db.execute(
        select(ShopMembership.shop_id, ShopMembership.role)
        .where(
            ShopMembership.user_account_id == auth.user.id,
            ShopMembership.is_active.is_(True),
        )
        .order_by(ShopMembership.id)
        .limit(2)
    ).all()
    if len(memberships) != 1 or memberships[0].role != auth.user.role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account does not have one valid active shop membership.",
        )
    return memberships[0].shop_id


def effective_shop_owner_id(db: Session, auth: AuthContext) -> int:
    """Return the canonical active owner of the authenticated Shop.

    Legacy business columns still require an `owner_user_id` compatibility
    value. Resolve it through the same membership boundary as authorization;
    never trust `UserAccount.shop_owner_id`, which can be stale or corrupted.
    """
    shop_id = effective_shop_id(db, auth)
    owner_id = db.scalar(
        select(ShopMembership.user_account_id)
        .join(UserAccount, UserAccount.id == ShopMembership.user_account_id)
        .where(
            ShopMembership.shop_id == shop_id,
            ShopMembership.role == "owner",
            ShopMembership.is_active.is_(True),
            UserAccount.role == "owner",
            UserAccount.is_active.is_(True),
        )
        .order_by(ShopMembership.id)
        .limit(1)
    )
    if owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This shop does not have one valid active owner.",
        )
    return owner_id


def require_role(auth: AuthContext, *allowed: str) -> None:
    if auth.user.role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role does not have access to this action.",
        )


def require_verified_email_if_present(auth: AuthContext) -> None:
    """Require mailbox proof for accounts created with an email address.

    Legacy bootstrapped owners and technicians have no email, so they remain
    usable until an explicit account-profile flow gives them one. A self-
    service signup always has an email and stays limited to session recovery
    routes until verification succeeds.
    """
    if auth.user.email is not None and auth.user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification is required before using this workflow.",
        )


def require_verified_auth_context(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
) -> AuthContext:
    require_verified_email_if_present(auth)
    return auth


def require_owner_context(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
) -> AuthContext:
    """Route dependency for endpoints available to Shop operators.

    Owners and managers can operate the Shop. Technicians can log in, clock
    in/out, and view/update only their own assigned work orders, diagnostic
    findings, and inspections via
    `require_owner_or_technician_context` below plus store-level scoping in
    `work_order_store.py`, `diagnostics_store.py`, and `inspection_store.py`.
    """
    require_role(auth, "owner", "manager")
    require_verified_email_if_present(auth)
    return auth


def require_owner_or_technician_context(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
) -> AuthContext:
    """Route dependency for routes Shop operators and technicians can reach.

    Does not by itself scope *which* rows a technician can see — the store
    layer (e.g. `work_order_store._work_order_query`) still filters a
    technician down to their membership Shop and own profile/assignments via
    `effective_shop_id` plus explicit `assigned_technician_id` checks.
    """
    require_role(auth, "owner", "manager", "technician")
    require_verified_email_if_present(auth)
    return auth
