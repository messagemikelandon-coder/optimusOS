from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id, hash_password, normalize_username
from app.config import Settings
from app.db_models import Shop, ShopEvent, ShopMembership, ShopSettings, UserAccount
from app.models import (
    ShopMembershipRead,
    ShopRead,
    ShopRole,
    ShopSettingsRead,
    ShopSignupRequest,
    ShopStatus,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ShopStoreError(Exception):
    pass


class ShopNotFoundError(ShopStoreError):
    pass


class ShopSignupError(ShopStoreError):
    pass


class ShopSignupConflictError(ShopSignupError):
    """Raised for a username/email that is already registered.

    The public-facing `message` is deliberately the same generic text for
    every conflict reason (security review finding on PR #57: distinct
    "username taken" vs. "email taken" messages let an unauthenticated
    caller enumerate registered accounts by varying one field at a time).
    `reason` carries the specific cause for the security-event log only --
    it must never be included in an HTTP response body.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


_SIGNUP_CONFLICT_MESSAGE = "Unable to create an account with these details."


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if not _EMAIL_RE.fullmatch(normalized):
        raise ShopSignupError("Email address is invalid.")
    return normalized


def signup_shop_owner(db: Session, settings: Settings, payload: ShopSignupRequest) -> UserAccount:
    """Self-service shop signup (/goal Phase 4): creates a brand-new owner
    `UserAccount` plus its own `Shop`/`ShopSettings`/`ShopMembership`/
    `ShopEvent`, all in one transaction. Deliberately does not log the new
    owner in itself -- the caller (the `/api/signup` route) does that,
    matching the same session/cookie flow `/api/auth/login` already uses.

    Real validation only: username and (normalized, case-insensitive)
    email must each be unique platform-wide. Checked explicitly here first
    so the common case produces a clean, specific-reason error rather than
    a raw `IntegrityError` -- but a plain pre-check `SELECT` is inherently
    racy (two concurrent signups for the same username/email can both pass
    it before either `INSERT` lands), so the actual `db.flush()` below is
    also wrapped to catch the database's own unique-constraint violation
    for that race, matching the established pattern already used for the
    identical race in `app/technician_store.py::provision_technician_login`.
    No email-verification step yet (that's /goal Phase 5/6's own
    requirement) -- the account is usable immediately, matching this
    app's existing bootstrap/synthetic-owner accounts, which are also
    unverified.
    """
    username = normalize_username(payload.username)
    email_normalized = _normalize_email(payload.email)

    if db.scalar(select(UserAccount).where(UserAccount.username == username)) is not None:
        raise ShopSignupConflictError(_SIGNUP_CONFLICT_MESSAGE, reason="username_taken")
    if (
        db.scalar(select(UserAccount).where(UserAccount.email_normalized == email_normalized))
        is not None
    ):
        raise ShopSignupConflictError(_SIGNUP_CONFLICT_MESSAGE, reason="email_taken")

    owner = UserAccount(
        username=username,
        display_name=payload.owner_display_name,
        role="owner",
        email=payload.email.strip(),
        email_normalized=email_normalized,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(owner)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ShopSignupConflictError(_SIGNUP_CONFLICT_MESSAGE, reason="race_conflict") from None
    create_shop_for_new_owner(
        db,
        settings,
        owner,
        display_name=payload.business_name,
        created_via="self_service_signup",
    )
    db.commit()
    db.refresh(owner)
    return owner


def _shop_for_owner(db: Session, auth: AuthContext) -> Shop:
    """Resolve the Shop the authenticated user belongs to.

    Phase 3 slice 1 only creates one shop per pre-existing owner (via the
    migration backfill) and does not yet move business-table scoping onto
    `shop_id` -- this bridges the pre-existing `effective_owner_id`
    tenant boundary to the new Shop model via the owner's own
    `ShopMembership` row, without changing how any other store module
    scopes data yet. That migration is a later, separate slice.
    """
    owner_id = effective_owner_id(auth)
    shop = db.scalar(
        select(Shop)
        .join(ShopMembership, ShopMembership.shop_id == Shop.id)
        .where(
            ShopMembership.user_account_id == owner_id,
            ShopMembership.role == ShopRole.OWNER.value,
            ShopMembership.is_active.is_(True),
        )
        .order_by(Shop.id)
    )
    if shop is None:
        raise ShopNotFoundError("No shop is associated with this account.")
    return shop


def resolve_shop_id_for_owner(db: Session, owner_id: int) -> int | None:
    """Best-effort `shop_id` lookup for populating new business-table rows
    at create time (/goal Phase 3 slice 4), given an already-resolved
    shop-owning `UserAccount.id` (i.e. the same value `effective_owner_id`
    would return).

    Returns `None` rather than raising when no shop is found -- unlike
    `_shop_for_owner`/`get_current_shop`, which are used for routes that
    should hard-fail without a shop, a create path should not suddenly
    start rejecting requests over what was, when this function was
    written, still a nullable column. In practice this only returns
    `None` for an account created by a path this repo hasn't wired to
    `create_shop_for_new_owner` yet -- every real owner (bootstrapped,
    migrated, or synthetic-provisioned) always has a shop.

    Since /goal Phase 3 slice 6 (`alembic/versions/025_shop_id_not_null.py`),
    `shop_id` is NOT NULL on every one of this function's ~15 call sites'
    target tables -- a `None` return today surfaces as an unhandled
    Postgres `IntegrityError` (a loud 500, not silent data corruption) at
    whichever call site hits it, rather than a clean domain error.
    Independent review of that slice flagged this as a latent (not
    currently reachable) robustness gap; tracked in
    `docs/context/KNOWN_ISSUES.md` rather than fixed immediately, since a
    proper fix (raising a clear exception here) needs matching exception
    handling audited at every call site, not just this function.
    """
    return db.scalar(
        select(ShopMembership.shop_id)
        .where(
            ShopMembership.user_account_id == owner_id,
            ShopMembership.role == ShopRole.OWNER.value,
            ShopMembership.is_active.is_(True),
        )
        .order_by(ShopMembership.shop_id)
    )


def resolve_shop_id(db: Session, auth: AuthContext) -> int | None:
    """`resolve_shop_id_for_owner` for the common case where an `AuthContext`
    (rather than an already-resolved owner id) is what the caller has."""
    return resolve_shop_id_for_owner(db, effective_owner_id(auth))


def _to_read(shop: Shop) -> ShopRead:
    return ShopRead(
        id=shop.id,
        legal_business_name=shop.legal_business_name,
        display_name=shop.display_name,
        address_line_1=shop.address_line_1,
        address_line_2=shop.address_line_2,
        city=shop.city,
        state=shop.state,
        postal_code=shop.postal_code,
        country=shop.country,
        phone=shop.phone,
        email=shop.email,
        timezone=shop.timezone,
        currency=shop.currency,
        status=ShopStatus(shop.status),
        created_at=shop.created_at,
        updated_at=shop.updated_at,
    )


def _settings_to_read(settings: ShopSettings) -> ShopSettingsRead:
    return ShopSettingsRead(
        shop_id=settings.shop_id,
        labor_rate=float(settings.labor_rate) if settings.labor_rate is not None else None,
        mobile_service_fee=(
            float(settings.mobile_service_fee) if settings.mobile_service_fee is not None else None
        ),
        shop_supplies_percent=(
            float(settings.shop_supplies_percent)
            if settings.shop_supplies_percent is not None
            else None
        ),
        parts_tax_rate=(
            float(settings.parts_tax_rate) if settings.parts_tax_rate is not None else None
        ),
        operating_hours=settings.operating_hours,
        service_area=settings.service_area,
        estimate_terms_text=settings.estimate_terms_text,
        invoice_terms_text=settings.invoice_terms_text,
        payment_plan_settings=settings.payment_plan_settings,
        branding_reference=settings.branding_reference,
    )


def _membership_to_read(membership: ShopMembership) -> ShopMembershipRead:
    return ShopMembershipRead(
        id=membership.id,
        shop_id=membership.shop_id,
        user_account_id=membership.user_account_id,
        role=ShopRole(membership.role),
        is_active=membership.is_active,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


def create_shop_for_new_owner(
    db: Session,
    settings: Settings,
    owner: UserAccount,
    *,
    display_name: str | None = None,
    created_via: str = "bootstrap_owner_account",
) -> Shop:
    """Create a Shop + ShopSettings + owner ShopMembership for a brand-new
    owner account.

    A fresh install runs `alembic upgrade head` before any owner account
    exists (see docs/context/RELEASE_CHECKLIST.md's runbook order), so
    the migration's own backfill (which only covers owners that already
    exist at migration time, i.e. an existing deployment being upgraded)
    never fires for a fresh install -- `bootstrap_owner_account` is the
    only code that runs for that case, so it must create the Shop itself
    or a fresh install would end up with an owner but no shop at all.
    Mirrors alembic/versions/022_shop_tenant_model.py's backfill logic:
    real config values only, no fabricated fields.

    `display_name` defaults to `settings.business_name` (the existing
    single-shop behavior: bootstrap/synthetic-owner paths always create
    "Landon Motor Works"). Self-service signup (/goal Phase 4) passes an
    explicit `display_name` instead -- a new shop must never inherit the
    one hardcoded business name meant for the original pilot shop.
    `created_via` only affects the audit event's `actor_name`, letting
    the resulting `ShopEvent` distinguish how the shop came to exist.
    """
    shop = Shop(display_name=display_name or settings.business_name, status=ShopStatus.ACTIVE.value)
    db.add(shop)
    db.flush()

    db.add(
        ShopSettings(
            shop_id=shop.id,
            labor_rate=settings.labor_rate,
            mobile_service_fee=settings.mobile_service_fee,
            shop_supplies_percent=settings.shop_supplies_percent,
            parts_tax_rate=settings.parts_tax_rate,
        )
    )
    db.add(
        ShopMembership(
            shop_id=shop.id,
            user_account_id=owner.id,
            role=ShopRole.OWNER.value,
        )
    )
    db.add(
        ShopEvent(
            shop_id=shop.id,
            event_type="shop_created_for_new_owner",
            actor_name=created_via,
            event_metadata={"owner_user_account_id": owner.id},
        )
    )
    db.flush()
    return shop


def get_current_shop(db: Session, auth: AuthContext) -> ShopRead:
    return _to_read(_shop_for_owner(db, auth))


def get_current_shop_settings(db: Session, auth: AuthContext) -> ShopSettingsRead:
    shop = _shop_for_owner(db, auth)
    if shop.settings is None:
        raise ShopNotFoundError("This shop has no settings row.")
    return _settings_to_read(shop.settings)


def list_current_shop_memberships(db: Session, auth: AuthContext) -> list[ShopMembershipRead]:
    shop = _shop_for_owner(db, auth)
    memberships = db.scalars(
        select(ShopMembership).where(ShopMembership.shop_id == shop.id).order_by(ShopMembership.id)
    ).all()
    return [_membership_to_read(membership) for membership in memberships]
