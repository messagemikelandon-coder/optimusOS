from __future__ import annotations

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (
    AuthContext,
    effective_shop_id,
    end_impersonation_session,
    ensure_utc,
    is_shop_access_suspended_readonly,
    start_impersonation_session,
)
from app.config import Settings
from app.db_models import AuthSession, Shop, ShopEvent, ShopMembership, UserAccount
from app.models import SupportShopListResponse, SupportShopSummary
from app.subscription_store import count_active_technician_seats

__all__ = [
    "SupportNotFoundError",
    "SupportStoreError",
    "end_shop_impersonation",
    "impersonate_shop_owner",
    "list_shops_for_support",
]


class SupportStoreError(ValueError):
    pass


class SupportNotFoundError(SupportStoreError):
    pass


def _owner_for(db: Session, shop_id: int) -> UserAccount | None:
    """Mirrors `effective_shop_owner_id`'s stricter membership+account
    check (independent-review finding) rather than trusting
    `ShopMembership.role` alone -- this is the resolution step for the
    highest-privilege action in the app (impersonation), so it should fail
    closed the same way the rest of the codebase already does."""
    return db.scalar(
        select(UserAccount)
        .join(ShopMembership, ShopMembership.user_account_id == UserAccount.id)
        .where(
            ShopMembership.shop_id == shop_id,
            ShopMembership.role == "owner",
            ShopMembership.is_active.is_(True),
            UserAccount.role == "owner",
            UserAccount.is_active.is_(True),
            UserAccount.account_status == "active",
        )
        .order_by(ShopMembership.id)
        .limit(1)
    )


def list_shops_for_support(db: Session) -> SupportShopListResponse:
    """Read-only, cross-shop directory for the platform support role
    (/goal Phase 8). This is the one deliberate, disclosed exception to
    this codebase's `effective_shop_id`-scoping rule that every other
    store module follows -- a support account's entire purpose is
    visibility across every shop, not access to any one shop's business
    data (customers, invoices, estimates, etc. are never touched here).

    Uses `is_shop_access_suspended_readonly` (never `sync_shop_access_status`,
    which corrects the cached `Shop.status` and commits a `ShopEvent`) --
    a read-only directory must never write to a shop the caller isn't even
    authenticated as, which every shop's page load would otherwise do
    whenever its cached status had drifted (a real defect caught by
    independent review before this slice shipped)."""
    shops = db.scalars(select(Shop).order_by(Shop.id)).all()
    items: list[SupportShopSummary] = []
    for shop in shops:
        owner = _owner_for(db, shop.id)
        member_count = (
            db.scalar(
                select(func.count())
                .select_from(ShopMembership)
                .where(ShopMembership.shop_id == shop.id, ShopMembership.is_active.is_(True))
            )
            or 0
        )
        subscription = shop.subscription
        is_suspended = is_shop_access_suspended_readonly(shop)
        items.append(
            SupportShopSummary(
                shop_id=shop.id,
                display_name=shop.display_name,
                status=shop.status,
                created_at=ensure_utc(shop.created_at),
                owner_username=owner.username if owner else None,
                owner_display_name=owner.display_name if owner else None,
                member_count=member_count,
                subscription_tier=subscription.tier if subscription else None,
                subscription_billing_status=subscription.billing_status if subscription else None,
                seat_limit=subscription.seat_limit if subscription else None,
                seats_used=count_active_technician_seats(db, shop.id),
                trial_ends_at=(
                    ensure_utc(subscription.trial_ends_at)
                    if subscription and subscription.trial_ends_at
                    else None
                ),
                is_access_suspended=is_suspended,
            )
        )
    return SupportShopListResponse(items=items)


def impersonate_shop_owner(
    db: Session, auth: AuthContext, *, settings: Settings, shop_id: int, request: Request
) -> tuple[str, AuthSession, UserAccount]:
    """Mint a real, time-boxed session as `shop_id`'s owner, initiated by a
    support account (/goal Phase 8). Deliberately targets only the owner --
    an owner already has full authority over that shop's managers and
    technicians, so impersonating the owner is "all access to all
    functions" for that shop without inventing a second privilege tier.
    Logs a `ShopEvent` on the target shop itself (not just a security-log
    line) so a future audit surface for that shop's own owner can show
    that support acted on their behalf -- this is a disclosed, auditable
    action, not a silent one."""
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise SupportNotFoundError("Shop not found.")
    owner = _owner_for(db, shop_id)
    if owner is None:
        raise SupportNotFoundError("This shop has no active owner to impersonate.")
    token, auth_session = start_impersonation_session(
        db=db, settings=settings, target_owner=owner, impersonator=auth.user, request=request
    )
    db.add(
        ShopEvent(
            shop_id=shop_id,
            event_type="support_impersonation_started",
            actor_user_account_id=auth.user.id,
            actor_name=auth.user.display_name,
            event_metadata={"support_username": auth.user.username, "owner_id": owner.id},
        )
    )
    db.commit()
    return token, auth_session, owner


def end_shop_impersonation(
    db: Session, auth: AuthContext, *, settings: Settings, request: Request
) -> tuple[str, AuthSession, UserAccount]:
    """Revoke the current impersonated-owner session and return the browser
    to the originating support account. Logs a `ShopEvent` on the shop that
    was being impersonated, mirroring the start event, before the session
    (and therefore `effective_shop_id`) is gone."""
    shop_id = effective_shop_id(db, auth)
    token, new_session = end_impersonation_session(
        db=db, settings=settings, auth=auth, request=request
    )
    support_user = db.get(UserAccount, new_session.user_id)
    assert support_user is not None
    db.add(
        ShopEvent(
            shop_id=shop_id,
            event_type="support_impersonation_ended",
            actor_user_account_id=support_user.id,
            actor_name=support_user.display_name,
            event_metadata={"support_username": support_user.username},
        )
    )
    db.commit()
    return token, new_session, support_user
