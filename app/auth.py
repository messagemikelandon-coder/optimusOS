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
from app.db_models import (
    AuthSession,
    Shop,
    ShopEvent,
    ShopMembership,
    ShopSubscription,
    UserAccount,
)

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


def _support_exists_query() -> Select[tuple[int]]:
    return select(func.count()).select_from(UserAccount).where(UserAccount.role == "support")


def bootstrap_support_account(settings: Settings | None = None, db: Session | None = None) -> int:
    """/goal Phase 8: platform-side-only provisioning for the read-only
    support role, mirroring `bootstrap_owner_account`'s idempotent shape.
    Deliberately creates no Shop/ShopSettings/ShopMembership -- a support
    account is not scoped to any single shop, by design."""
    resolved_settings = settings or get_settings()
    managed_session = db is None
    session = db or build_session_factory(resolved_settings.database_url)()
    try:
        support_count = session.scalar(_support_exists_query()) or 0
        if support_count > 0:
            print("Support account already present.")
            return 0

        if (
            not resolved_settings.optimus_support_username
            or not resolved_settings.optimus_support_password
        ):
            print(
                "Support bootstrap skipped: OPTIMUS_SUPPORT_USERNAME or "
                "OPTIMUS_SUPPORT_PASSWORD missing."
            )
            return 1

        support_user = UserAccount(
            username=normalize_username(resolved_settings.optimus_support_username),
            display_name="Support",
            role="support",
            password_hash=hash_password(resolved_settings.optimus_support_password),
            is_active=True,
        )
        session.add(support_user)
        session.commit()
        print("Support account created.")
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
    # /goal Phase 8: a support account has no ShopMembership at all, by
    # design -- exempt from this check the same way get_current_auth_context is.
    if user.role != "support":
        effective_shop_id(db, AuthContext(user=user, session=auth_session))
    user.last_login_at = datetime.now(UTC)
    db.add(user)
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    auth_session.expires_at = ensure_utc(auth_session.expires_at)
    return token, auth_session


# /goal Phase 8: deliberately short-lived compared to a normal session
# (session_ttl_hours defaults to 12) -- impersonation should require a
# fresh, explicit start rather than lingering unattended for a full
# workday.
IMPERSONATION_SESSION_TTL_MINUTES = 60


def start_impersonation_session(
    *,
    db: Session,
    settings: Settings,
    target_owner: UserAccount,
    impersonator: UserAccount,
    request: Request,
) -> tuple[str, AuthSession]:
    """Mint a brand-new session for `target_owner` (a real shop's owner
    account), reusing `create_auth_session`'s exact mechanics so the
    resulting session behaves identically to a normal owner login for
    every existing route -- no new access-control branching anywhere else
    in the app. Tagged with `impersonated_by_user_account_id` so it is
    always auditable and time-boxed shorter than a normal session."""
    token, auth_session = create_auth_session(
        db=db, settings=settings, user=target_owner, request=request
    )
    auth_session.expires_at = datetime.now(UTC) + timedelta(
        minutes=IMPERSONATION_SESSION_TTL_MINUTES
    )
    auth_session.impersonated_by_user_account_id = impersonator.id
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    auth_session.expires_at = ensure_utc(auth_session.expires_at)
    return token, auth_session


def end_impersonation_session(
    *, db: Session, settings: Settings, auth: AuthContext, request: Request
) -> tuple[str, AuthSession]:
    """Revoke the current impersonated-owner session and mint a fresh
    session for the original support account, so ending impersonation
    returns the browser to the support directory rather than leaving it
    signed in as the shop owner or logging it out entirely."""
    impersonator_id = auth.session.impersonated_by_user_account_id
    if impersonator_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This session is not an impersonation session.",
        )
    # Lock the session row first (independent-review finding): without
    # this, a concurrent double-submit -- two tabs, a client retry -- could
    # both read revoked_at as still-None and each revoke+re-mint, producing
    # two live support sessions and duplicate ended events.
    locked_session = db.execute(
        select(AuthSession).where(AuthSession.id == auth.session.id).with_for_update()
    ).scalar_one()
    if locked_session.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This impersonation session has already been ended.",
        )
    impersonator = db.get(UserAccount, impersonator_id)
    if impersonator is None or impersonator.role != "support" or not impersonator.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The originating support account is no longer valid.",
        )
    locked_session.revoked_at = datetime.now(UTC)
    db.add(locked_session)
    db.commit()
    return create_auth_session(db=db, settings=settings, user=impersonator, request=request)


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
        # /goal Phase 8: a support account is deliberately not scoped to any
        # single shop -- it has no ShopMembership row at all, so it is the
        # one role exempt from this check.
        if user.role != "support":
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


def is_shop_access_suspended_readonly(shop: Shop) -> bool:
    """Pure, read-only derivation of whether `shop`'s access is currently
    suspended -- unlike `sync_shop_access_status`, this never writes to the
    database (no cache correction, no `ShopEvent`, no commit). Used by the
    platform support directory (/goal Phase 8), which reads across every
    shop on the platform and must stay genuinely read-only -- a support
    session loading the directory must never trigger a write to a shop it
    isn't even authenticated as."""
    subscription = shop.subscription
    if subscription is None:
        return True
    return _is_subscription_access_suspended(subscription, datetime.now(UTC))


def _is_subscription_access_suspended(subscription: ShopSubscription, now: datetime) -> bool:
    # Every writer of "trialing"/"past_due" also sets the matching expiry
    # timestamp in the same write (start_trial, refresh_subscription_from_square),
    # so a missing one here should never happen in practice -- but a status
    # naming an expiry with no expiry set is treated as suspended, not as
    # unrestricted access, matching this function's fail-closed contract for
    # every other unexpected case (see the final `return True` below).
    status_value = subscription.billing_status
    if status_value == "active":
        return False
    if status_value == "trialing":
        return subscription.trial_ends_at is None or now > ensure_utc(subscription.trial_ends_at)
    if status_value == "past_due":
        return subscription.grace_period_ends_at is None or now > ensure_utc(
            subscription.grace_period_ends_at
        )
    if status_value == "canceled":
        if subscription.current_period_end is None:
            return True
        return now > ensure_utc(subscription.current_period_end)
    return True


def sync_shop_access_status(db: Session, shop: Shop) -> bool:
    """Recompute whether `shop` should be suspended right now from its
    subscription's real timestamps -- never trust the cached `Shop.status`
    alone, matching this codebase's existing derived-field convention for
    invoice status/balance. Corrects the cache (and logs a `ShopEvent`) only
    when the derived state actually changed. Returns True if access is
    currently suspended.

    Called on every business-route request via `require_shop_access_active`
    below, so a trial or grace period expiring is enforced immediately
    without needing a background job to notice it first.
    """
    subscription = shop.subscription
    if subscription is None:
        # Every shop-creation path in this codebase creates a subscription
        # row in the same transaction as the shop itself (a real trial for
        # self-service signup, a grandfathered row for bootstrap/synthetic
        # owners, migration 031's backfill for pre-existing shops) -- this
        # should never happen. Fail closed rather than silently granting
        # access to a shop this code cannot account for.
        return True
    now = datetime.now(UTC)
    suspended = _is_subscription_access_suspended(subscription, now)
    if suspended:
        new_status = "cancelled" if subscription.billing_status == "canceled" else "suspended"
    else:
        new_status = "active"
    if shop.status != new_status:
        old_status = shop.status
        shop.status = new_status
        db.add(shop)
        db.add(
            ShopEvent(
                shop_id=shop.id,
                event_type="shop_suspended" if suspended else "shop_reactivated",
                event_metadata={
                    "from_status": old_status,
                    "to_status": new_status,
                    "billing_status": subscription.billing_status,
                },
            )
        )
        db.commit()
    return suspended


def require_shop_access_active(db: Session, auth: AuthContext) -> None:
    shop_id = effective_shop_id(db, auth)
    shop = db.get(Shop, shop_id)
    if shop is None or sync_shop_access_status(db, shop):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "This shop's OptimusOS subscription is not active. An owner or "
                "manager must resolve billing to restore access."
            ),
        )


def require_owner_context(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: DbSessionDep,
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
    require_shop_access_active(db, auth)
    return auth


def require_owner_only_context(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: DbSessionDep,
) -> AuthContext:
    """Route dependency for owner-exclusive actions.

    Stricter than `require_owner_context` (which also admits managers): only
    the shop *owner* passes. Used by post-signup operating-mode onboarding --
    an invited manager, a technician, a support account, or an unauthenticated
    caller must never be able to complete another account's first-run mode
    selection.
    """
    require_role(auth, "owner")
    require_verified_email_if_present(auth)
    require_shop_access_active(db, auth)
    return auth


def require_owner_or_technician_context(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
    db: DbSessionDep,
) -> AuthContext:
    """Route dependency for routes Shop operators and technicians can reach.

    Does not by itself scope *which* rows a technician can see — the store
    layer (e.g. `work_order_store._work_order_query`) still filters a
    technician down to their membership Shop and own profile/assignments via
    `effective_shop_id` plus explicit `assigned_technician_id` checks.
    """
    require_role(auth, "owner", "manager", "technician")
    require_verified_email_if_present(auth)
    require_shop_access_active(db, auth)
    return auth


def require_billing_context(
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
) -> AuthContext:
    """Route dependency for the billing surface itself: owners and managers
    only, but deliberately does *not* call `require_shop_access_active` --
    a suspended shop must still be able to view its billing status and add
    a payment method to restore access, or suspension would be permanent."""
    require_role(auth, "owner", "manager")
    require_verified_email_if_present(auth)
    return auth


def reconcile_abandoned_impersonation_sessions(db: Session, support_user_id: int) -> None:
    """Independent-review finding: a support account that lets an
    impersonation session merely expire (TTL) or abandons it (tab closed,
    cookie cleared) instead of calling end-impersonation would otherwise
    leave the target shop's audit trail with a `support_impersonation_started`
    event and no matching end event -- no reliable way to tell "properly
    ended" from "abandoned," nor a trustworthy end-of-access timestamp.

    There is no background scheduler in this codebase, so this closes the
    gap lazily: every time this support account is next active anywhere
    (in practice, every support-gated request, starting with the directory
    view it always lands on), sweep its own impersonation sessions that
    have expired without ever being explicitly revoked and close them out
    with a matching audit event."""
    now = datetime.now(UTC)
    abandoned = db.scalars(
        select(AuthSession).where(
            AuthSession.impersonated_by_user_account_id == support_user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at <= now,
        )
    ).all()
    if not abandoned:
        return
    support_user = db.get(UserAccount, support_user_id)
    for session in abandoned:
        shop_id = db.scalar(
            select(ShopMembership.shop_id).where(
                ShopMembership.user_account_id == session.user_id,
                ShopMembership.role == "owner",
                ShopMembership.is_active.is_(True),
            )
        )
        session.revoked_at = now
        db.add(session)
        if shop_id is not None:
            db.add(
                ShopEvent(
                    shop_id=shop_id,
                    event_type="support_impersonation_expired",
                    actor_user_account_id=support_user_id,
                    actor_name=support_user.display_name if support_user else None,
                    event_metadata={"auth_session_id": session.id},
                )
            )
    db.commit()


def require_support_context(
    db: DbSessionDep,
    auth: Annotated[AuthContext, Depends(get_current_auth_context)],
) -> AuthContext:
    """Route dependency for the platform-side, read-only support directory
    (/goal Phase 8). Support-only, and deliberately does not call
    `require_shop_access_active`/`effective_shop_id` at all -- a support
    account has no single shop to be scoped to; its whole purpose is
    reading across every shop."""
    require_role(auth, "support")
    reconcile_abandoned_impersonation_sessions(db, auth.user.id)
    return auth
