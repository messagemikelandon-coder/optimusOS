from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id, ensure_utc, sync_shop_access_status
from app.config import Settings
from app.db_models import Shop, ShopEvent, ShopSubscription, Technician
from app.models import (
    SubscriptionBillingStatus,
    SubscriptionEventRead,
    SubscriptionEventsResponse,
    SubscriptionRead,
    SubscriptionTier,
)
from app.services.square import SquareSubscriptionClient

__all__ = [
    "SUBSCRIPTION_TIERS",
    "SubscriptionConflictError",
    "SubscriptionStoreError",
    "add_payment_method",
    "cancel_subscription",
    "change_tier",
    "count_active_technician_seats",
    "get_subscription",
    "grandfather_subscription",
    "list_subscription_events",
    "refresh_subscription_from_square",
    "start_trial",
    "subscribe",
]

TRIAL_DAYS = 14
GRACE_PERIOD_DAYS = 7

# Real, owner-confirmed seat-based pricing (not a placeholder): one
# technician seat = one non-archived `Technician` profile for the shop,
# counted in `count_active_technician_seats`. Stored per-subscription as a
# snapshot in `ShopSubscription.seat_limit` at selection time, so a future
# change to this table never silently changes what an existing subscriber
# already agreed to.
SUBSCRIPTION_TIERS: dict[str, dict[str, Any]] = {
    "solo": {"display_name": "Solo", "price_cents": 4900, "seat_limit": 1},
    "team": {"display_name": "Team", "price_cents": 9900, "seat_limit": 5},
    "shop": {"display_name": "Shop", "price_cents": 19900, "seat_limit": None},
}


class SubscriptionStoreError(ValueError):
    pass


class SubscriptionConflictError(SubscriptionStoreError):
    pass


def _plan_variation_id(settings: Settings, tier: str) -> str:
    return {
        "solo": settings.square_solo_plan_variation_id,
        "team": settings.square_team_plan_variation_id,
        "shop": settings.square_shop_plan_variation_id,
    }[tier]


def _parse_square_charged_through_date(value: Any) -> datetime | None:
    """Square's Subscription object reports `charged_through_date` as a bare
    `YYYY-MM-DD` string (the last day already paid for), not a timestamp --
    treat the subscriber as covered through the end of that day."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=UTC
        )
    except ValueError:
        return None


def _require_subscription(
    db: Session, auth: AuthContext, *, for_update: bool = False
) -> tuple[Shop, ShopSubscription]:
    shop_id = effective_shop_id(db, auth)
    shop = db.get(Shop, shop_id)
    if shop is None or shop.subscription is None:
        raise SubscriptionStoreError("This shop has no subscription record.")
    if for_update:
        db.refresh(shop.subscription, with_for_update=True)
    return shop, shop.subscription


def count_active_technician_seats(db: Session, shop_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Technician)
            .where(Technician.shop_id == shop_id, Technician.is_archived.is_(False))
        )
        or 0
    )


def start_trial(db: Session, *, shop_id: int) -> ShopSubscription:
    """Called once, in the same transaction as shop creation, for brand-new
    self-service signups only (`app/shop_store.py::signup_shop_owner`).
    Bootstrap/synthetic shop creation calls `grandfather_subscription`
    instead -- see that function's docstring for why."""
    trial_ends_at = datetime.now(UTC) + timedelta(days=TRIAL_DAYS)
    subscription = ShopSubscription(
        shop_id=shop_id,
        tier=SubscriptionTier.SOLO.value,
        billing_status=SubscriptionBillingStatus.TRIALING.value,
        seat_limit=SUBSCRIPTION_TIERS["solo"]["seat_limit"],
        trial_ends_at=trial_ends_at,
    )
    db.add(subscription)
    db.flush()
    db.add(
        ShopEvent(
            shop_id=shop_id,
            event_type="trial_started",
            event_metadata={"tier": "solo", "trial_ends_at": trial_ends_at.isoformat()},
        )
    )
    return subscription


def grandfather_subscription(db: Session, *, shop_id: int, actor_name: str) -> ShopSubscription:
    """Bootstrap/synthetic shop creation: an unlimited-seat, already-active
    subscription with no trial timer and no Square objects, so an existing
    real business is never put on a countdown it did not agree to. Mirrors
    migration 031's own backfill for shops that already existed before this
    slice."""
    subscription = ShopSubscription(
        shop_id=shop_id,
        tier=SubscriptionTier.SHOP.value,
        billing_status=SubscriptionBillingStatus.ACTIVE.value,
        seat_limit=None,
    )
    db.add(subscription)
    db.flush()
    db.add(
        ShopEvent(shop_id=shop_id, event_type="subscription_grandfathered", actor_name=actor_name)
    )
    return subscription


def _to_read(db: Session, shop: Shop, subscription: ShopSubscription) -> SubscriptionRead:
    suspended = sync_shop_access_status(db, shop)
    return SubscriptionRead(
        tier=SubscriptionTier(subscription.tier),
        billing_status=SubscriptionBillingStatus(subscription.billing_status),
        seat_limit=subscription.seat_limit,
        seats_used=count_active_technician_seats(db, shop.id),
        trial_ends_at=ensure_utc(subscription.trial_ends_at)
        if subscription.trial_ends_at
        else None,
        current_period_start=(
            ensure_utc(subscription.current_period_start)
            if subscription.current_period_start
            else None
        ),
        current_period_end=(
            ensure_utc(subscription.current_period_end) if subscription.current_period_end else None
        ),
        grace_period_ends_at=(
            ensure_utc(subscription.grace_period_ends_at)
            if subscription.grace_period_ends_at
            else None
        ),
        canceled_at=ensure_utc(subscription.canceled_at) if subscription.canceled_at else None,
        has_payment_method=subscription.square_card_id is not None,
        is_access_suspended=suspended,
        shop_status=shop.status,
    )


def get_subscription(db: Session, auth: AuthContext) -> SubscriptionRead:
    shop, subscription = _require_subscription(db, auth)
    return _to_read(db, shop, subscription)


def list_subscription_events(db: Session, auth: AuthContext) -> SubscriptionEventsResponse:
    shop_id = effective_shop_id(db, auth)
    events = db.scalars(
        select(ShopEvent)
        .where(
            ShopEvent.shop_id == shop_id,
            ShopEvent.event_type.in_(
                (
                    "trial_started",
                    "subscription_grandfathered",
                    "payment_method_added",
                    "subscription_started",
                    "subscription_refreshed",
                    "tier_changed",
                    "subscription_canceled",
                    "shop_suspended",
                    "shop_reactivated",
                )
            ),
        )
        .order_by(ShopEvent.created_at, ShopEvent.id)
    ).all()
    return SubscriptionEventsResponse(
        items=[
            SubscriptionEventRead(
                id=event.id,
                event_type=event.event_type,
                actor_name=event.actor_name,
                event_metadata=event.event_metadata,
                created_at=ensure_utc(event.created_at),
            )
            for event in events
        ]
    )


def add_payment_method(
    db: Session, auth: AuthContext, *, client: SquareSubscriptionClient, source_id: str
) -> SubscriptionRead:
    shop, subscription = _require_subscription(db, auth, for_update=True)
    owner_email = auth.user.email
    if not owner_email:
        raise SubscriptionStoreError("An account email is required before adding a payment method.")
    customer = subscription.square_customer_id and client.search_customer_by_email(owner_email)
    if not customer:
        customer = client.create_customer(
            idempotency_key=f"shop-{shop.id}:billing-customer",
            given_name=auth.user.display_name,
            email=owner_email,
        )
    card = client.create_card(
        idempotency_key=f"shop-{shop.id}:card:{source_id[:24]}",
        source_id=source_id,
        customer_id=str(customer["id"]),
    )
    subscription.square_customer_id = str(customer["id"])
    subscription.square_card_id = str(card["id"])
    db.add(subscription)
    db.add(
        ShopEvent(shop_id=shop.id, event_type="payment_method_added", actor_name=auth.user.username)
    )
    db.commit()
    db.refresh(subscription)
    return _to_read(db, shop, subscription)


def change_tier(
    db: Session,
    auth: AuthContext,
    *,
    settings: Settings,
    client: SquareSubscriptionClient | None,
    tier: SubscriptionTier,
) -> SubscriptionRead:
    shop, subscription = _require_subscription(db, auth, for_update=True)
    new_tier_info = SUBSCRIPTION_TIERS[tier.value]
    new_seat_limit = new_tier_info["seat_limit"]
    if new_seat_limit is not None:
        seats_used = count_active_technician_seats(db, shop.id)
        if seats_used > new_seat_limit:
            raise SubscriptionConflictError(
                f"This shop has {seats_used} technician seat(s) in use, which exceeds the "
                f"{new_tier_info['display_name']} tier's limit of {new_seat_limit}. Archive "
                "technicians before downgrading."
            )
    old_tier = subscription.tier
    if subscription.square_subscription_id and client is not None:
        plan_variation_id = _plan_variation_id(settings, tier.value)
        if not plan_variation_id:
            raise SubscriptionStoreError(
                f"The {new_tier_info['display_name']} tier is not yet billable "
                "(no Square plan variation configured)."
            )
        # Square subscriptions are re-pointed at a new plan variation via a
        # swap; this codebase's own sandbox scope does not yet implement
        # true proration -- the new price simply applies at the next
        # billing cycle, disclosed in docs/context/KNOWN_ISSUES.md.
        client.cancel_subscription(subscription.square_subscription_id)
        created = client.create_subscription(
            idempotency_key=f"shop-{shop.id}:resubscribe:{tier.value}",
            location_id=settings.square_location_id,
            customer_id=str(subscription.square_customer_id),
            card_id=str(subscription.square_card_id),
            plan_variation_id=plan_variation_id,
        )
        subscription.square_subscription_id = str(created["id"])
        subscription.current_period_start = datetime.now(UTC)
        subscription.current_period_end = _parse_square_charged_through_date(
            created.get("charged_through_date")
        )
    subscription.tier = tier.value
    subscription.seat_limit = new_seat_limit
    db.add(subscription)
    db.add(
        ShopEvent(
            shop_id=shop.id,
            event_type="tier_changed",
            actor_name=auth.user.username,
            event_metadata={"from_tier": old_tier, "to_tier": tier.value},
        )
    )
    db.commit()
    db.refresh(subscription)
    return _to_read(db, shop, subscription)


def subscribe(
    db: Session,
    auth: AuthContext,
    *,
    settings: Settings,
    client: SquareSubscriptionClient,
    tier: SubscriptionTier,
) -> SubscriptionRead:
    shop, subscription = _require_subscription(db, auth, for_update=True)
    if subscription.square_customer_id is None or subscription.square_card_id is None:
        raise SubscriptionStoreError("Add a payment method before subscribing to a paid tier.")
    if subscription.square_subscription_id:
        raise SubscriptionConflictError(
            "This shop already has an active Square subscription. Use tier change instead."
        )
    plan_variation_id = _plan_variation_id(settings, tier.value)
    if not plan_variation_id:
        raise SubscriptionStoreError(
            f"The {SUBSCRIPTION_TIERS[tier.value]['display_name']} tier is not yet billable "
            "(no Square plan variation configured)."
        )
    new_seat_limit = SUBSCRIPTION_TIERS[tier.value]["seat_limit"]
    if new_seat_limit is not None and count_active_technician_seats(db, shop.id) > new_seat_limit:
        raise SubscriptionConflictError(
            f"This shop's current technician count exceeds the {tier.value} tier's seat limit."
        )
    created = client.create_subscription(
        idempotency_key=f"shop-{shop.id}:subscribe:{tier.value}",
        location_id=settings.square_location_id,
        customer_id=str(subscription.square_customer_id),
        card_id=str(subscription.square_card_id),
        plan_variation_id=plan_variation_id,
    )
    subscription.tier = tier.value
    subscription.seat_limit = new_seat_limit
    subscription.billing_status = SubscriptionBillingStatus.ACTIVE.value
    subscription.square_subscription_id = str(created["id"])
    subscription.trial_ends_at = None
    subscription.grace_period_ends_at = None
    subscription.current_period_start = datetime.now(UTC)
    subscription.current_period_end = _parse_square_charged_through_date(
        created.get("charged_through_date")
    )
    db.add(subscription)
    db.add(
        ShopEvent(
            shop_id=shop.id,
            event_type="subscription_started",
            actor_name=auth.user.username,
            event_metadata={"tier": tier.value},
        )
    )
    db.commit()
    db.refresh(subscription)
    return _to_read(db, shop, subscription)


def cancel_subscription(
    db: Session, auth: AuthContext, *, client: SquareSubscriptionClient | None
) -> SubscriptionRead:
    shop, subscription = _require_subscription(db, auth, for_update=True)
    if subscription.square_subscription_id and client is not None:
        client.cancel_subscription(subscription.square_subscription_id)
    subscription.billing_status = SubscriptionBillingStatus.CANCELED.value
    subscription.canceled_at = datetime.now(UTC)
    # Access continues to the end of the already-paid-for period, not
    # immediately -- consistent with standard SaaS cancellation norms.
    if subscription.current_period_end is None:
        subscription.current_period_end = datetime.now(UTC)
    db.add(subscription)
    db.add(
        ShopEvent(
            shop_id=shop.id, event_type="subscription_canceled", actor_name=auth.user.username
        )
    )
    db.commit()
    db.refresh(subscription)
    return _to_read(db, shop, subscription)


def refresh_subscription_from_square(
    db: Session, auth: AuthContext, *, client: SquareSubscriptionClient
) -> SubscriptionRead:
    shop, subscription = _require_subscription(db, auth, for_update=True)
    if not subscription.square_subscription_id:
        raise SubscriptionStoreError("This shop has no live Square subscription to refresh.")
    square_subscription = client.get_subscription(subscription.square_subscription_id)
    square_status = str(square_subscription.get("status") or "").upper()
    charged_through = _parse_square_charged_through_date(
        square_subscription.get("charged_through_date")
    )
    if charged_through is not None:
        subscription.current_period_end = charged_through
    if square_status == "ACTIVE":
        subscription.billing_status = SubscriptionBillingStatus.ACTIVE.value
        subscription.grace_period_ends_at = None
    elif square_status in {"PENDING", "DEACTIVATED"}:
        if subscription.billing_status != SubscriptionBillingStatus.PAST_DUE.value:
            subscription.billing_status = SubscriptionBillingStatus.PAST_DUE.value
            subscription.grace_period_ends_at = datetime.now(UTC) + timedelta(
                days=GRACE_PERIOD_DAYS
            )
    elif square_status == "CANCELED":
        subscription.billing_status = SubscriptionBillingStatus.CANCELED.value
    db.add(subscription)
    db.add(
        ShopEvent(
            shop_id=shop.id,
            event_type="subscription_refreshed",
            actor_name=auth.user.username,
            event_metadata={"square_status": square_status},
        )
    )
    db.commit()
    db.refresh(subscription)
    return _to_read(db, shop, subscription)
