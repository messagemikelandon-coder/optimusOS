from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id
from app.config import Settings
from app.db_models import Shop, ShopEvent, ShopMembership, ShopSettings, UserAccount
from app.models import (
    ShopMembershipRead,
    ShopRead,
    ShopRole,
    ShopSettingsRead,
    ShopStatus,
)


class ShopStoreError(Exception):
    pass


class ShopNotFoundError(ShopStoreError):
    pass


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
    start rejecting requests over a still-nullable column. In practice
    this only returns `None` for an account created by a path this repo
    hasn't wired to `create_shop_for_new_owner` yet -- every real owner
    (bootstrapped, migrated, or synthetic-provisioned) always has a shop.
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


def create_shop_for_new_owner(db: Session, settings: Settings, owner: UserAccount) -> Shop:
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
    """
    shop = Shop(display_name=settings.business_name, status=ShopStatus.ACTIVE.value)
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
            actor_name="bootstrap_owner_account",
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
