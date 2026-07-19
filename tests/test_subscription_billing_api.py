from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.account_security_store import InvitationConflictError, accept_invitation, create_invitation
from app.auth import AuthContext, ensure_utc, require_owner_context, sync_shop_access_status
from app.config import Settings
from app.db_models import AuthSession, Shop, Technician, UserAccount
from app.models import (
    AddPaymentMethodRequest,
    ShopInvitationAccept,
    ShopInvitationCreate,
    ShopRole,
    SubscribeRequest,
    SubscriptionTier,
    TechnicianCreate,
)
from app.subscription_store import (
    SubscriptionConflictError,
    cancel_subscription,
    change_tier,
    count_active_technician_seats,
    get_subscription,
)
from app.technician_store import TechnicianConflictError, create_technician
from tests.test_account_security_api import RecordingEmailAdapter, _token_from_message
from tests.test_context_api import auth_context, create_user, raw_cookie_from_response
from tests.test_signup_api import signup

pytestmark = pytest.mark.anyio


class StubSquareSubscriptionClient:
    """Offline stand-in mirroring `tests/test_square_api.py::StubSquareClient`'s
    shape: records every call, returns canned Square-shaped payloads."""

    def __init__(self, *, status_value: str = "ACTIVE") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.status_value = status_value
        self.charged_through_date: str | None = None
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def search_customer_by_email(self, email: str) -> dict[str, Any] | None:
        self.calls.append(("search_customer_by_email", {"email": email}))
        return None

    def create_customer(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_customer", kwargs))
        return {"id": "SQ-CUST-1"}

    def create_card(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_card", kwargs))
        return {"id": "SQ-CARD-1"}

    def create_subscription(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_subscription", kwargs))
        return {"id": "SQ-SUB-1", "charged_through_date": self.charged_through_date}

    def cancel_subscription(self, square_subscription_id: str) -> dict[str, Any]:
        self.calls.append(("cancel_subscription", {"id": square_subscription_id}))
        return {"id": square_subscription_id, "status": "CANCELED"}

    def get_subscription(self, square_subscription_id: str) -> dict[str, Any]:
        self.calls.append(("get_subscription", {"id": square_subscription_id}))
        return {"id": square_subscription_id, "status": self.status_value}


def _configure_square_billing(settings: Settings) -> None:
    settings.square_access_token = "sandbox-test-token"
    settings.square_location_id = "L123"
    settings.square_environment = "sandbox"
    settings.square_solo_plan_variation_id = "PV-SOLO"
    settings.square_team_plan_variation_id = "PV-TEAM"
    settings.square_shop_plan_variation_id = "PV-SHOP"


def _install_stub(monkeypatch: pytest.MonkeyPatch, stub: StubSquareSubscriptionClient) -> None:
    monkeypatch.setattr(main, "SquareSubscriptionClient", lambda settings: stub)


def _auth_for(db: Session, user: UserAccount, suffix: str = "billing") -> AuthContext:
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=f"billing-{user.id}-{suffix}",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_seen_at=datetime.now(UTC),
    )
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    return AuthContext(user=user, session=auth_session)


def technician_payload(**overrides: Any) -> TechnicianCreate:
    base: dict[str, Any] = {
        "first_name": "Jordan",
        "last_name": "Reyes",
        "phone": None,
        "email": None,
        "employment_status": "Full-time",
        "job_title": "Technician",
        "hourly_cost": 28.5,
    }
    base.update(overrides)
    return TechnicianCreate(**base)


def _latest_shop(db: Session) -> Shop:
    shop = db.scalar(select(Shop).order_by(Shop.id.desc()))
    assert shop is not None
    return shop


def _verify_email(db: Session, auth: AuthContext) -> None:
    """Self-service signup always has an email and starts unverified (/goal
    Phase 5); these tests are about billing/suspension, not verification, so
    fast-forward past it directly rather than re-testing that separately-
    covered flow."""
    auth.user.email_verified_at = datetime.now(UTC)
    db.add(auth.user)
    db.commit()


def test_bootstrap_owner_is_grandfathered_with_unlimited_active_subscription(
    settings, db_session: Session
) -> None:
    shop = db_session.scalar(select(Shop))
    assert shop is not None
    subscription = shop.subscription
    assert subscription is not None
    assert subscription.tier == "shop"
    assert subscription.billing_status == "active"
    assert subscription.seat_limit is None
    assert subscription.trial_ends_at is None
    assert sync_shop_access_status(db_session, shop) is False
    assert shop.status == "active"


async def test_self_service_signup_gets_a_real_14_day_trial(settings, db_session: Session) -> None:
    _payload, response = await signup(settings, db_session, username="trial-owner")
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _verify_email(db_session, auth)
    shop = _latest_shop(db_session)
    subscription = shop.subscription
    assert subscription is not None
    assert subscription.tier == "solo"
    assert subscription.billing_status == "trialing"
    assert subscription.seat_limit == 1
    assert subscription.trial_ends_at is not None
    now = datetime.now(UTC)
    assert ensure_utc(subscription.trial_ends_at) > now + timedelta(days=13)
    assert ensure_utc(subscription.trial_ends_at) < now + timedelta(days=15)
    assert sync_shop_access_status(db_session, shop) is False
    assert require_owner_context(auth, db_session) is auth


async def test_expired_trial_suspends_business_access_but_not_billing(
    settings, db_session: Session
) -> None:
    _payload, response = await signup(settings, db_session, username="expired-owner")
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _verify_email(db_session, auth)
    shop = _latest_shop(db_session)
    subscription = shop.subscription
    assert subscription is not None
    subscription.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    db_session.add(subscription)
    db_session.commit()

    assert sync_shop_access_status(db_session, shop) is True
    db_session.refresh(shop)
    assert shop.status == "suspended"
    with pytest.raises(HTTPException) as excinfo:
        require_owner_context(auth, db_session)
    assert excinfo.value.status_code == 402

    # Billing itself must remain reachable so the owner can fix payment --
    # get_subscription() does not call require_shop_access_active.
    read = get_subscription(db_session, auth)
    assert read.is_access_suspended is True
    assert read.shop_status == "suspended"


async def test_reactivating_a_suspended_shop_restores_access(settings, db_session: Session) -> None:
    _payload, response = await signup(settings, db_session, username="recovering-owner")
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _verify_email(db_session, auth)
    shop = _latest_shop(db_session)
    subscription = shop.subscription
    assert subscription is not None
    subscription.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    db_session.add(subscription)
    db_session.commit()
    assert sync_shop_access_status(db_session, shop) is True

    subscription.billing_status = "active"
    subscription.trial_ends_at = None
    db_session.add(subscription)
    db_session.commit()

    assert sync_shop_access_status(db_session, shop) is False
    db_session.refresh(shop)
    assert shop.status == "active"
    assert require_owner_context(auth, db_session) is auth


async def test_seat_limit_rejects_creating_a_technician_beyond_the_tier(
    settings, db_session: Session
) -> None:
    _payload, response = await signup(settings, db_session, username="solo-owner")
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    create_technician(db=db_session, auth=auth, payload=technician_payload())
    with pytest.raises(TechnicianConflictError):
        create_technician(db=db_session, auth=auth, payload=technician_payload(first_name="Second"))


async def test_archiving_a_technician_frees_a_seat(settings, db_session: Session) -> None:
    _payload, response = await signup(settings, db_session, username="solo-owner-2")
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    first = create_technician(db=db_session, auth=auth, payload=technician_payload())
    with pytest.raises(TechnicianConflictError):
        create_technician(db=db_session, auth=auth, payload=technician_payload(first_name="Second"))

    technician = db_session.get(Technician, first.id)
    assert technician is not None
    technician.is_archived = True
    db_session.add(technician)
    db_session.commit()

    created = create_technician(
        db=db_session, auth=auth, payload=technician_payload(first_name="Third")
    )
    assert created.first_name == "Third"


def test_grandfathered_unlimited_shop_has_no_seat_limit(settings, db_session: Session) -> None:
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    auth = _auth_for(db_session, owner)
    for index in range(6):
        create_technician(
            db=db_session, auth=auth, payload=technician_payload(first_name=f"Tech{index}")
        )
    shop = db_session.scalar(select(Shop))
    assert shop is not None
    assert count_active_technician_seats(db_session, shop.id) == 6


async def test_add_payment_method_and_subscribe_real_flow(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _payload, response = await signup(settings, db_session, username="paying-owner")
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _configure_square_billing(settings)
    stub = StubSquareSubscriptionClient()
    _install_stub(monkeypatch, stub)

    payment_result = await main.add_billing_payment_method(
        AddPaymentMethodRequest(source_id="cnon:card-nonce-ok"), db_session, settings, auth
    )
    assert payment_result.has_payment_method is True

    subscribed = await main.subscribe_billing(
        SubscribeRequest(tier=SubscriptionTier.TEAM), db_session, settings, auth
    )
    assert subscribed.tier == SubscriptionTier.TEAM
    assert subscribed.billing_status.value == "active"
    assert subscribed.trial_ends_at is None
    steps = [name for name, _ in stub.calls]
    assert steps == ["create_customer", "create_card", "create_subscription"]


def test_downgrade_rejected_when_seats_exceed_new_tier_limit(settings, db_session: Session) -> None:
    # The grandfathered bootstrap subscription has no square_subscription_id,
    # so change_tier's Square-calling branch never fires here -- client=None
    # is the honest choice, matching cancel_subscription's own use of it below.
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    auth = _auth_for(db_session, owner)
    change_tier(db_session, auth, settings=settings, client=None, tier=SubscriptionTier.TEAM)
    for index in range(3):
        create_technician(
            db=db_session, auth=auth, payload=technician_payload(first_name=f"T{index}")
        )
    with pytest.raises(SubscriptionConflictError):
        change_tier(db_session, auth, settings=settings, client=None, tier=SubscriptionTier.SOLO)


async def test_cancel_subscription_keeps_access_derived_from_period_end(
    settings, db_session: Session
) -> None:
    _payload, response = await signup(settings, db_session, username="cancel-owner")
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    result = cancel_subscription(db_session, auth, client=None)
    assert result.billing_status.value == "canceled"
    shop = _latest_shop(db_session)
    # current_period_end defaults to "now" when never set by a real Square
    # subscription, so a never-paid trial cancellation suspends immediately
    # -- a real paid subscriber's current_period_end would be in the future.
    assert sync_shop_access_status(db_session, shop) is True


async def test_refresh_moves_pending_square_status_into_a_grace_period(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _payload, response = await signup(settings, db_session, username="refresh-owner")
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _configure_square_billing(settings)
    stub = StubSquareSubscriptionClient(status_value="ACTIVE")
    _install_stub(monkeypatch, stub)
    await main.add_billing_payment_method(
        AddPaymentMethodRequest(source_id="cnon:card-nonce-ok"), db_session, settings, auth
    )
    await main.subscribe_billing(
        SubscribeRequest(tier=SubscriptionTier.SOLO), db_session, settings, auth
    )

    stub.status_value = "PENDING"
    refreshed = await main.refresh_billing_subscription(db_session, settings, auth)
    assert refreshed.billing_status.value == "past_due"
    assert refreshed.grace_period_ends_at is not None
    assert refreshed.grace_period_ends_at > datetime.now(UTC) + timedelta(days=6)


async def test_subscription_data_is_shop_scoped(settings, db_session: Session) -> None:
    _payload, response = await signup(settings, db_session, username="isolated-owner")
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    other_owner = create_user(
        db_session,
        username="other-billing-owner",
        password="other-owner-password-123",
        settings=settings,
    )
    other_auth = _auth_for(db_session, other_owner)

    mine = get_subscription(db_session, owner_auth)
    theirs = get_subscription(db_session, other_auth)
    assert mine.tier == "solo"
    assert theirs.tier == "shop"


async def test_technician_invitation_acceptance_is_seat_limit_gated(
    settings, db_session: Session
) -> None:
    """Security-review finding: invitation acceptance is the other code path
    (besides technician_store.create_technician) that can create a brand-new
    Technician row, and it must be gated by the same seat limit or a shop
    could staff past what it pays for."""
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    owner_auth = _auth_for(db_session, owner, "invite-owner")

    shop = db_session.scalar(select(Shop))
    assert shop is not None
    subscription = shop.subscription
    assert subscription is not None
    subscription.tier = "solo"
    subscription.seat_limit = 1
    db_session.add(subscription)
    db_session.commit()

    first_adapter = RecordingEmailAdapter()
    first_invitation = create_invitation(
        db_session,
        settings,
        owner_auth,
        ShopInvitationCreate(email="first-tech@example.com", role=ShopRole.TECHNICIAN),
        first_adapter,
    )
    first_token = _token_from_message(first_adapter.messages[0])
    accept_invitation(
        db_session,
        ShopInvitationAccept(
            token=first_token,
            display_name="First Tech",
            username="first-invited-tech",
            password="invited-password-123",
        ),
    )
    assert count_active_technician_seats(db_session, shop.id) == 1

    second_adapter = RecordingEmailAdapter()
    second_invitation = create_invitation(
        db_session,
        settings,
        owner_auth,
        ShopInvitationCreate(email="second-tech@example.com", role=ShopRole.TECHNICIAN),
        second_adapter,
    )
    second_token = _token_from_message(second_adapter.messages[0])
    with pytest.raises(InvitationConflictError):
        accept_invitation(
            db_session,
            ShopInvitationAccept(
                token=second_token,
                display_name="Second Tech",
                username="second-invited-tech",
                password="invited-password-123",
            ),
        )
    # The second acceptance must not have left a half-created account behind.
    assert (
        db_session.scalar(
            select(UserAccount.id).where(UserAccount.username == "second-invited-tech")
        )
        is None
    )
    assert count_active_technician_seats(db_session, shop.id) == 1
    assert first_invitation.id != second_invitation.id


async def test_subscribe_captures_period_end_so_cancellation_grants_a_real_grace_window(
    settings, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Correctness-review finding: cancellation is supposed to keep access
    through the already-paid-for period, but nothing previously captured
    Square's real `charged_through_date` into `current_period_end`, so every
    cancellation suspended immediately regardless of a real future period."""
    _payload, response = await signup(settings, db_session, username="grace-owner")
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _configure_square_billing(settings)
    future_period_end = (datetime.now(UTC) + timedelta(days=20)).strftime("%Y-%m-%d")
    stub = StubSquareSubscriptionClient()
    stub.charged_through_date = future_period_end
    _install_stub(monkeypatch, stub)

    await main.add_billing_payment_method(
        AddPaymentMethodRequest(source_id="cnon:card-nonce-ok"), db_session, settings, auth
    )
    subscribed = await main.subscribe_billing(
        SubscribeRequest(tier=SubscriptionTier.SOLO), db_session, settings, auth
    )
    assert subscribed.current_period_end is not None
    assert subscribed.current_period_end > datetime.now(UTC) + timedelta(days=19)

    result = await main.cancel_billing_subscription(db_session, settings, auth)
    assert result.billing_status.value == "canceled"
    assert result.current_period_end is not None
    assert result.current_period_end > datetime.now(UTC) + timedelta(days=19)
    shop = _latest_shop(db_session)
    assert sync_shop_access_status(db_session, shop) is False
