"""Unit coverage for ADR-022 post-signup operating-mode onboarding
(`GET /api/operating-mode/onboarding` and
`POST /api/operating-mode/onboarding/complete`).

Onboarding is owner-exclusive, reuses the mode-transition service's locking +
capability matrix, records `Shop.operating_mode_confirmed_at`, and writes
exactly one `post_signup_onboarding` audit event -- including for a deliberate
no-op confirmation of the default `shop` mode. It never touches tier, seats,
or business data, and never enforces or changes the bays observe gate.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main as main
from app.db import get_db_session, get_settings
from app.db_models import (
    AuthSession,
    Bay,
    Shop,
    ShopEvent,
    ShopMembership,
    UserAccount,
)
from app.models import (
    BayCreate,
    CapabilityId,
    CapabilityLevel,
    ModeOnboardingCompleteRequest,
    OperatingMode,
)
from tests.test_capabilities_api import _auth_for, _manager_for, _owner, _set_mode_and_tier
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_role_isolation import _create_technician as _create_technician_user

pytestmark = pytest.mark.anyio


async def _owner_auth(settings, db_session: Session):
    _, response = await login_as(settings, db_session)
    return auth_context(settings, db_session, raw_cookie_from_response(response))


def _shop_of(db_session: Session, owner: UserAccount) -> Shop:
    membership = db_session.scalar(
        select(ShopMembership).where(
            ShopMembership.user_account_id == owner.id,
            ShopMembership.role == "owner",
            ShopMembership.is_active.is_(True),
        )
    )
    assert membership is not None
    shop = db_session.get(Shop, membership.shop_id)
    assert shop is not None
    return shop


def _mark_confirmed(db_session: Session, shop: Shop) -> None:
    shop.operating_mode_confirmed_at = datetime.now(UTC)
    db_session.commit()


# --- Status ----------------------------------------------------------------


async def test_status_reports_needs_onboarding_for_unconfirmed_shop(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    shop = _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    assert shop.operating_mode_confirmed_at is None  # brand-new shop
    auth = _auth_for(db_session, owner, "status-unconfirmed")

    status = await main.get_operating_mode_onboarding_status(db_session, auth)
    assert status.needs_onboarding is True
    assert status.operating_mode == OperatingMode.SHOP
    assert status.confirmed_at is None


async def test_status_reports_confirmed_shop_does_not_need_onboarding(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    shop = _set_mode_and_tier(db_session, owner, mode="solo", tier="shop")
    _mark_confirmed(db_session, shop)
    auth = _auth_for(db_session, owner, "status-confirmed")

    status = await main.get_operating_mode_onboarding_status(db_session, auth)
    assert status.needs_onboarding is False
    assert status.operating_mode == OperatingMode.SOLO
    assert status.confirmed_at is not None


# --- Completion: changed and same-mode --------------------------------------


async def test_completion_with_changed_mode_updates_mode_and_confirms(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "complete-changed")

    result = await main.complete_operating_mode_onboarding(
        ModeOnboardingCompleteRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
        ),
        db_session,
        auth,
    )
    assert result.previous_mode == OperatingMode.SHOP
    assert result.new_mode == OperatingMode.SOLO
    assert result.changed is True
    assert result.confirmed_at is not None
    assert result.capabilities.operating_mode == OperatingMode.SOLO
    levels = {e.id: e.level for e in result.capabilities.capabilities}
    assert levels[CapabilityId.BAYS] == CapabilityLevel.HIDDEN

    # Both the mode change and the confirmation persisted atomically.
    db_session.expire_all()
    shop = _shop_of(db_session, owner)
    assert shop.operating_mode == "solo"
    assert shop.operating_mode_confirmed_at is not None


async def test_completion_keeping_default_shop_still_records_confirmation(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    shop = _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    assert shop.operating_mode_confirmed_at is None
    auth = _auth_for(db_session, owner, "complete-default")

    result = await main.complete_operating_mode_onboarding(
        ModeOnboardingCompleteRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SHOP
        ),
        db_session,
        auth,
    )
    # No mode change, but the deliberate confirmation is still recorded...
    assert result.changed is False
    assert result.new_mode == OperatingMode.SHOP
    assert result.confirmed_at is not None
    db_session.expire_all()
    shop = _shop_of(db_session, owner)
    assert shop.operating_mode_confirmed_at is not None

    # ...and it writes exactly one event even though nothing changed (unlike
    # the Settings apply, which is silent on a no-op).
    events = db_session.scalars(
        select(ShopEvent).where(
            ShopEvent.shop_id == shop.id,
            ShopEvent.event_type == "operating_mode_onboarding_completed",
        )
    ).all()
    assert len(events) == 1
    assert events[0].event_metadata is not None
    assert events[0].event_metadata["changed"] is False


async def test_completion_writes_exactly_one_event_with_expected_metadata(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    shop = _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "complete-audit")

    await main.complete_operating_mode_onboarding(
        ModeOnboardingCompleteRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.MOBILE_FIELD
        ),
        db_session,
        auth,
    )
    events = db_session.scalars(
        select(ShopEvent).where(
            ShopEvent.shop_id == shop.id,
            ShopEvent.event_type == "operating_mode_onboarding_completed",
        )
    ).all()
    assert len(events) == 1
    event = events[0]
    assert event.actor_user_account_id == owner.id
    assert event.actor_name == owner.username
    assert event.event_metadata is not None
    assert event.event_metadata["from_mode"] == "shop"
    assert event.event_metadata["to_mode"] == "mobile_field"
    assert event.event_metadata["changed"] is True
    assert event.event_metadata["source"] == "post_signup_onboarding"
    assert "confirmed_at" in event.event_metadata


# --- Optimistic concurrency -------------------------------------------------


async def test_completion_rejects_stale_expected_mode_with_409(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "complete-stale")

    # The shop already moved to mobile_field (e.g. another tab) first.
    await main.complete_operating_mode_onboarding(
        ModeOnboardingCompleteRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.MOBILE_FIELD
        ),
        db_session,
        auth,
    )
    with pytest.raises(HTTPException) as excinfo:
        await main.complete_operating_mode_onboarding(
            ModeOnboardingCompleteRequest(
                expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409


# --- Tier / seats / data untouched ------------------------------------------


async def test_completion_does_not_alter_tier_or_seats(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    shop = _set_mode_and_tier(db_session, owner, mode="shop", tier="team")
    assert shop.subscription is not None
    tier_before = shop.subscription.tier
    seat_before = shop.subscription.seat_limit
    auth = _auth_for(db_session, owner, "complete-tier")

    result = await main.complete_operating_mode_onboarding(
        ModeOnboardingCompleteRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
        ),
        db_session,
        auth,
    )
    assert result.capabilities.tier.value == tier_before
    db_session.expire_all()
    reloaded = _shop_of(db_session, owner)
    assert reloaded.subscription is not None
    assert reloaded.subscription.tier == tier_before
    assert reloaded.subscription.seat_limit == seat_before


async def test_completion_does_not_delete_business_data(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    shop = _shop_of(db_session, owner)
    await main.create_bay_record(BayCreate(name="Onboarding Bay"), db_session, auth)
    bays_before = db_session.scalar(
        select(func.count()).select_from(Bay).where(Bay.shop_id == shop.id)
    )

    # Switch to Solo (which hides bays) -- the rows must remain, only hidden.
    await main.complete_operating_mode_onboarding(
        ModeOnboardingCompleteRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
        ),
        db_session,
        auth,
    )
    bays_after = db_session.scalar(
        select(func.count()).select_from(Bay).where(Bay.shop_id == shop.id)
    )
    assert bays_after == bays_before
    assert bays_after and bays_after > 0


# --- Tenant isolation -------------------------------------------------------


async def test_completion_is_isolated_per_shop(settings, db_session: Session) -> None:
    owner_a = _owner(db_session)
    _set_mode_and_tier(db_session, owner_a, mode="shop", tier="shop")
    owner_b = create_user(db_session, username="second-owner", password="second-pass-123")
    shop_b = _set_mode_and_tier(db_session, owner_b, mode="shop", tier="shop")
    auth_a = _auth_for(db_session, owner_a, "iso-onboard-a")

    await main.complete_operating_mode_onboarding(
        ModeOnboardingCompleteRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
        ),
        db_session,
        auth_a,
    )
    # Shop B untouched: neither its mode nor its (still-unconfirmed) state moved.
    db_session.expire_all()
    reloaded_b = db_session.get(Shop, shop_b.id)
    assert reloaded_b is not None
    assert reloaded_b.operating_mode == "shop"
    assert reloaded_b.operating_mode_confirmed_at is None


# --- Auth: owner only; manager/technician/support/unauth denied -------------


async def test_manager_cannot_complete_onboarding(settings, db_session: Session) -> None:
    from app.auth import require_owner_only_context

    owner = _owner(db_session)
    manager = _manager_for(db_session, owner)
    auth = _auth_for(db_session, manager, "manager-denied")
    with pytest.raises(HTTPException) as excinfo:
        require_owner_only_context(auth, db_session)
    assert excinfo.value.status_code == 403


def test_support_cannot_complete_onboarding(settings, db_session: Session) -> None:
    from app.auth import hash_password, require_owner_only_context

    support = UserAccount(
        username="support-onboard",
        display_name="Support",
        role="support",
        password_hash=hash_password("support-password-123"),
        is_active=True,
    )
    db_session.add(support)
    db_session.commit()
    db_session.refresh(support)
    session = AuthSession(
        user_id=support.id,
        token_hash="support-onboard-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(session)
    db_session.commit()
    from app.auth import AuthContext

    with pytest.raises(HTTPException) as excinfo:
        require_owner_only_context(AuthContext(user=support, session=session), db_session)
    assert excinfo.value.status_code == 403


def test_onboarding_routes_enforce_owner_only_end_to_end(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    _create_technician_user(db_session, shop_owner_id=owner.id)
    _manager_for(db_session, owner)

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        complete_body = {"expected_current_mode": "shop", "proposed_mode": "solo"}

        # Unauthenticated -> 401 on both.
        assert client.get("/api/operating-mode/onboarding").status_code == 401
        assert (
            client.post("/api/operating-mode/onboarding/complete", json=complete_body).status_code
            == 401
        )

        # Owner -> allowed (status read).
        assert (
            client.post(
                "/api/auth/login", json={"username": "owner", "password": "owner-password-123"}
            ).status_code
            == 200
        )
        assert client.get("/api/operating-mode/onboarding").status_code == 200
        client.post("/api/auth/logout")

        # Manager -> 403 (owner-exclusive, stricter than the Settings routes).
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "capabilities-manager", "password": "manager-password-123"},
            ).status_code
            == 200
        )
        assert client.get("/api/operating-mode/onboarding").status_code == 403
        assert (
            client.post("/api/operating-mode/onboarding/complete", json=complete_body).status_code
            == 403
        )
        client.post("/api/auth/logout")

        # Technician -> 403.
        assert (
            client.post(
                "/api/auth/login", json={"username": "tech-one", "password": "tech-password-123"}
            ).status_code
            == 200
        )
        assert client.get("/api/operating-mode/onboarding").status_code == 403
        assert (
            client.post("/api/operating-mode/onboarding/complete", json=complete_body).status_code
            == 403
        )
    finally:
        main.app.dependency_overrides.clear()


# --- Bays stay observe-only; OpenAPI additive ------------------------------


async def test_bays_remain_observe_only_after_onboarding(
    settings, db_session: Session, caplog
) -> None:
    auth = await _owner_auth(settings, db_session)
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    created = await main.create_bay_record(BayCreate(name="Neutral Bay"), db_session, auth)

    await main.complete_operating_mode_onboarding(
        ModeOnboardingCompleteRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
        ),
        db_session,
        auth,
    )
    with caplog.at_level(logging.INFO, logger="optimus"):
        caplog.clear()
        fetched = await main.get_bay_record(created.id, db_session, auth)
    assert fetched.id == created.id  # bay still fully readable in solo mode

    observed = [
        r
        for r in caplog.records
        if getattr(r, "security_event", None) == "authz.capability_observed"
    ]
    assert len(observed) == 1
    assert observed[0].decision == "would_deny"  # type: ignore[attr-defined]


def test_onboarding_openapi_is_additive_only() -> None:
    schema = main.app.openapi()
    paths = schema["paths"]
    assert "/api/operating-mode/onboarding" in paths
    assert "/api/operating-mode/onboarding/complete" in paths
    assert "get" in paths["/api/operating-mode/onboarding"]
    assert "post" in paths["/api/operating-mode/onboarding/complete"]
    # Pre-existing surfaces unchanged.
    assert set(paths["/api/bays"].keys()) >= {"get", "post"}
    assert "post" in paths["/api/operating-mode/apply"]
