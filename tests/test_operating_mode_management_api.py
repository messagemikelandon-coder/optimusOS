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
    Appointment,
    Bay,
    ScheduleBlock,
    ShopEvent,
    ShopMembership,
    Technician,
    UserAccount,
    WorkingHours,
)
from app.models import (
    AppointmentCreate,
    BayCreate,
    CapabilityId,
    CapabilityLevel,
    CustomerCreate,
    ModeTransitionApplyRequest,
    ModeTransitionPreviewRequest,
    OperatingMode,
    TechnicianCreate,
    VehicleCreate,
)
from tests.test_capabilities_api import _auth_for, _manager_for, _owner, _set_mode_and_tier
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_role_isolation import _create_technician as _create_technician_user

pytestmark = pytest.mark.anyio

_ALL_MODES = ["solo", "mobile_field", "shop"]


async def _owner_auth(settings, db_session: Session):
    _, response = await login_as(settings, db_session)
    return auth_context(settings, db_session, raw_cookie_from_response(response))


def _shop_id_of(db_session: Session, owner: UserAccount) -> int:
    membership = db_session.scalar(
        select(ShopMembership).where(
            ShopMembership.user_account_id == owner.id,
            ShopMembership.role == "owner",
            ShopMembership.is_active.is_(True),
        )
    )
    assert membership is not None
    return membership.shop_id


# --- Preview matrix: all nine (from, to) mode combinations ------------------


@pytest.mark.parametrize("from_mode", _ALL_MODES)
@pytest.mark.parametrize("to_mode", _ALL_MODES)
async def test_preview_matrix_for_all_transitions(
    settings, db_session: Session, from_mode: str, to_mode: str
) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode=from_mode, tier="shop")
    auth = _auth_for(db_session, owner, f"preview-{from_mode}-{to_mode}")

    preview = await main.preview_operating_mode_change(
        ModeTransitionPreviewRequest(proposed_mode=OperatingMode(to_mode)), db_session, auth
    )

    assert preview.current_mode == OperatingMode(from_mode)
    assert preview.proposed_mode == OperatingMode(to_mode)
    assert preview.is_noop is (from_mode == to_mode)
    assert preview.no_data_deleted is True
    assert "deleted" in preview.data_handling_statement.lower()

    if from_mode == to_mode:
        assert preview.capability_changes == []
        assert preview.would_be_hidden == []
    else:
        # capability_changes must exactly match the two matrices' diff.
        from app.capability_store import capability_levels_for

        cur = capability_levels_for(OperatingMode(from_mode), "owner")
        prop = capability_levels_for(OperatingMode(to_mode), "owner")
        expected_changed = {cid for cid in CapabilityId if cur[cid] != prop[cid]}
        assert {c.id for c in preview.capability_changes} == expected_changed
        for change in preview.capability_changes:
            assert change.from_level == cur[change.id]
            assert change.to_level == prop[change.id]


async def test_preview_would_be_hidden_on_shop_to_solo(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "hidden-shop-solo")

    preview = await main.preview_operating_mode_change(
        ModeTransitionPreviewRequest(proposed_mode=OperatingMode.SOLO), db_session, auth
    )
    # Bays and technicians become hidden in Solo mode.
    assert CapabilityId.BAYS in preview.would_be_hidden
    assert CapabilityId.TECHNICIANS in preview.would_be_hidden


# --- Existing-data warnings + no-deletion proof -----------------------------


async def _seed_all_categories(settings, db_session: Session, auth) -> dict[str, int]:
    """Create one row in each warning category for the owner's shop."""
    owner = _owner(db_session)
    shop_id = _shop_id_of(db_session, owner)

    await main.create_bay_record(BayCreate(name="Bay 1"), db_session, auth)
    technician = await main.create_technician_record(
        TechnicianCreate(first_name="Alex", last_name="Reyes"), db_session, auth
    )
    customer = await main.create_customer_record(
        CustomerCreate(first_name="Jamie", last_name="Diaz"), db_session, auth
    )
    vehicle = await main.create_vehicle_record(
        customer.id, VehicleCreate(year=2020, make="Toyota", model="Camry"), db_session, auth
    )
    start = datetime.now(UTC) + timedelta(hours=48)
    await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer.id,
            vehicle_id=vehicle.id,
            technician_id=technician.id,
            service_type="Oil change",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )
    db_session.add(
        WorkingHours(
            owner_user_id=owner.id,
            shop_id=shop_id,
            technician_id=technician.id,
            day_of_week=1,
            start_minute=540,
            end_minute=1020,
        )
    )
    db_session.add(
        ScheduleBlock(
            owner_user_id=owner.id,
            shop_id=shop_id,
            start_time=start,
            end_time=start + timedelta(hours=2),
            reason="Maintenance",
        )
    )
    db_session.commit()
    return {
        "bays": db_session.scalar(
            select(func.count()).select_from(Bay).where(Bay.shop_id == shop_id)
        )
        or 0,
        "technicians": db_session.scalar(
            select(func.count()).select_from(Technician).where(Technician.shop_id == shop_id)
        )
        or 0,
        "appointments": db_session.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.shop_id == shop_id)
        )
        or 0,
        "working_hours": db_session.scalar(
            select(func.count()).select_from(WorkingHours).where(WorkingHours.shop_id == shop_id)
        )
        or 0,
        "schedule_blocks": db_session.scalar(
            select(func.count()).select_from(ScheduleBlock).where(ScheduleBlock.shop_id == shop_id)
        )
        or 0,
    }


async def test_preview_warns_about_existing_data_on_shop_to_solo(
    settings, db_session: Session
) -> None:
    auth = await _owner_auth(settings, db_session)
    _set_mode_and_tier(db_session, _owner(db_session), mode="shop", tier="shop")
    counts = await _seed_all_categories(settings, db_session, auth)
    assert all(c > 0 for c in counts.values())

    preview = await main.preview_operating_mode_change(
        ModeTransitionPreviewRequest(proposed_mode=OperatingMode.SOLO), db_session, auth
    )

    warned = {w.category for w in preview.warnings}
    # All five categories have data and all are reduced in Solo mode.
    assert warned == {"bays", "technicians", "appointments", "working_hours", "schedule_blocks"}
    for w in preview.warnings:
        assert w.count >= 1
        # Every warning reassures the owner that data is retained, never lost.
        msg = w.message.lower()
        assert "retained" in msg or "nothing is deleted" in msg or "never deleted" in msg
    assert set(preview.retained_data_categories) == warned


async def test_apply_deletes_no_data(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    _set_mode_and_tier(db_session, _owner(db_session), mode="shop", tier="shop")
    before = await _seed_all_categories(settings, db_session, auth)

    await main.apply_operating_mode_change(
        ModeTransitionApplyRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
        ),
        db_session,
        auth,
    )

    owner = _owner(db_session)
    shop_id = _shop_id_of(db_session, owner)
    after = {
        "bays": db_session.scalar(
            select(func.count()).select_from(Bay).where(Bay.shop_id == shop_id)
        ),
        "technicians": db_session.scalar(
            select(func.count()).select_from(Technician).where(Technician.shop_id == shop_id)
        ),
        "appointments": db_session.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.shop_id == shop_id)
        ),
        "working_hours": db_session.scalar(
            select(func.count()).select_from(WorkingHours).where(WorkingHours.shop_id == shop_id)
        ),
        "schedule_blocks": db_session.scalar(
            select(func.count()).select_from(ScheduleBlock).where(ScheduleBlock.shop_id == shop_id)
        ),
    }
    assert after == before  # nothing hidden was deleted or archived


# --- Apply: success, audit, capability snapshot -----------------------------


async def test_apply_changes_mode_and_capability_snapshot(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "apply-snapshot")

    result = await main.apply_operating_mode_change(
        ModeTransitionApplyRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
        ),
        db_session,
        auth,
    )

    assert result.previous_mode == OperatingMode.SHOP
    assert result.new_mode == OperatingMode.SOLO
    assert result.changed is True
    # Fresh snapshot reflects the new mode.
    assert result.capabilities.operating_mode == OperatingMode.SOLO
    levels = {e.id: e.level for e in result.capabilities.capabilities}
    assert levels[CapabilityId.BAYS] == CapabilityLevel.HIDDEN
    # Persisted.
    shop_id = _shop_id_of(db_session, owner)
    from app.db_models import Shop

    persisted = db_session.get(Shop, shop_id)
    assert persisted is not None and persisted.operating_mode == "solo"


async def test_apply_writes_exactly_one_audit_event(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "apply-audit")
    shop_id = _shop_id_of(db_session, owner)

    await main.apply_operating_mode_change(
        ModeTransitionApplyRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.MOBILE_FIELD
        ),
        db_session,
        auth,
    )

    events = db_session.scalars(
        select(ShopEvent).where(
            ShopEvent.shop_id == shop_id, ShopEvent.event_type == "operating_mode_changed"
        )
    ).all()
    assert len(events) == 1
    event = events[0]
    assert event.actor_user_account_id == owner.id
    assert event.actor_name == owner.username
    assert event.event_metadata == {
        "from_mode": "shop",
        "to_mode": "mobile_field",
        "source": "operating_mode_management_api",
    }


async def test_apply_noop_when_proposed_equals_current_writes_no_event(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "apply-noop")
    shop_id = _shop_id_of(db_session, owner)

    result = await main.apply_operating_mode_change(
        ModeTransitionApplyRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SHOP
        ),
        db_session,
        auth,
    )
    assert result.changed is False
    assert result.new_mode == OperatingMode.SHOP
    events = db_session.scalars(
        select(ShopEvent).where(
            ShopEvent.shop_id == shop_id, ShopEvent.event_type == "operating_mode_changed"
        )
    ).all()
    assert events == []


# --- Optimistic concurrency -------------------------------------------------


async def test_apply_rejects_stale_expected_mode_with_409(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "apply-stale")

    # Someone already moved the shop to mobile_field; this caller still thinks
    # it is shop.
    await main.apply_operating_mode_change(
        ModeTransitionApplyRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.MOBILE_FIELD
        ),
        db_session,
        auth,
    )
    with pytest.raises(HTTPException) as excinfo:
        await main.apply_operating_mode_change(
            ModeTransitionApplyRequest(
                expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409


# --- Tier / seat untouched --------------------------------------------------


async def test_mode_change_does_not_alter_tier_or_seat_limit(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    shop = _set_mode_and_tier(db_session, owner, mode="shop", tier="team")
    assert shop.subscription is not None
    tier_before = shop.subscription.tier
    seat_before = shop.subscription.seat_limit
    auth = _auth_for(db_session, owner, "tier-untouched")

    result = await main.apply_operating_mode_change(
        ModeTransitionApplyRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
        ),
        db_session,
        auth,
    )
    assert result.capabilities.tier.value == tier_before
    db_session.expire_all()
    from app.db_models import Shop

    reloaded = db_session.get(Shop, shop.id)
    assert reloaded is not None and reloaded.subscription is not None
    assert reloaded.subscription.tier == tier_before
    assert reloaded.subscription.seat_limit == seat_before


# --- Tenant isolation -------------------------------------------------------


async def test_mode_change_is_isolated_per_shop(settings, db_session: Session) -> None:
    owner_a = _owner(db_session)
    _set_mode_and_tier(db_session, owner_a, mode="shop", tier="shop")
    owner_b = create_user(db_session, username="second-owner", password="second-pass-123")
    _set_mode_and_tier(db_session, owner_b, mode="shop", tier="shop")
    auth_a = _auth_for(db_session, owner_a, "iso-a")

    await main.apply_operating_mode_change(
        ModeTransitionApplyRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
        ),
        db_session,
        auth_a,
    )

    # Shop B is untouched -- the change only reached shop A.
    from app.db_models import Shop

    shop_b_id = _shop_id_of(db_session, owner_b)
    shop_b = db_session.get(Shop, shop_b_id)
    assert shop_b is not None and shop_b.operating_mode == "shop"


# --- Auth: owner/manager allowed; technician/support/unauth denied ----------


def test_operating_mode_routes_enforce_owner_or_manager_end_to_end(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    _create_technician_user(db_session, shop_owner_id=owner.id)

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        preview_body = {"proposed_mode": "solo"}
        apply_body = {"expected_current_mode": "shop", "proposed_mode": "solo"}

        # Unauthenticated -> 401 on both.
        assert client.post("/api/operating-mode/preview", json=preview_body).status_code == 401
        assert client.post("/api/operating-mode/apply", json=apply_body).status_code == 401

        # Owner -> allowed.
        assert (
            client.post(
                "/api/auth/login", json={"username": "owner", "password": "owner-password-123"}
            ).status_code
            == 200
        )
        assert client.post("/api/operating-mode/preview", json=preview_body).status_code == 200
        client.post("/api/auth/logout")

        # Technician -> 403 on both.
        assert (
            client.post(
                "/api/auth/login", json={"username": "tech-one", "password": "tech-password-123"}
            ).status_code
            == 200
        )
        assert client.post("/api/operating-mode/preview", json=preview_body).status_code == 403
        assert client.post("/api/operating-mode/apply", json=apply_body).status_code == 403
    finally:
        main.app.dependency_overrides.clear()


async def test_manager_can_preview_and_apply(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    manager = _manager_for(db_session, owner)
    auth = _auth_for(db_session, manager, "manager-apply")

    preview = await main.preview_operating_mode_change(
        ModeTransitionPreviewRequest(proposed_mode=OperatingMode.MOBILE_FIELD), db_session, auth
    )
    assert preview.current_mode == OperatingMode.SHOP

    result = await main.apply_operating_mode_change(
        ModeTransitionApplyRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.MOBILE_FIELD
        ),
        db_session,
        auth,
    )
    assert result.new_mode == OperatingMode.MOBILE_FIELD


def test_support_session_is_denied(settings, db_session: Session) -> None:
    """A support account (shop-less, platform role) has no owner/manager
    shop membership, so the same `require_owner_context` gate the routes use
    rejects it -- support can never change a shop's operating mode."""
    from datetime import timedelta

    from app.auth import AuthContext, hash_password, require_owner_context
    from app.db_models import AuthSession

    support = UserAccount(
        username="support-mode",
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
        token_hash="support-mode-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(session)
    db_session.commit()

    with pytest.raises(HTTPException) as excinfo:
        require_owner_context(AuthContext(user=support, session=session), db_session)
    assert excinfo.value.status_code == 403


# --- Invalid mode value -----------------------------------------------------


def test_invalid_mode_value_is_rejected_by_schema(settings, db_session: Session) -> None:
    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        client.post("/api/auth/login", json={"username": "owner", "password": "owner-password-123"})
        # "technician" is a role, never an operating mode.
        resp = client.post("/api/operating-mode/preview", json={"proposed_mode": "technician"})
        assert resp.status_code == 422
        resp2 = client.post(
            "/api/operating-mode/apply",
            json={"expected_current_mode": "shop", "proposed_mode": "enterprise"},
        )
        assert resp2.status_code == 422
    finally:
        main.app.dependency_overrides.clear()


# --- Bays stay observe-only + behavior-neutral; OpenAPI additive ------------


async def test_bays_remain_observe_only_and_behavior_neutral_after_mode_change(
    settings, db_session: Session, caplog
) -> None:
    auth = await _owner_auth(settings, db_session)
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    created = await main.create_bay_record(BayCreate(name="Neutral Bay"), db_session, auth)

    # Switch to solo (bays would_deny) and confirm bays still serve identically.
    await main.apply_operating_mode_change(
        ModeTransitionApplyRequest(
            expected_current_mode=OperatingMode.SHOP, proposed_mode=OperatingMode.SOLO
        ),
        db_session,
        auth,
    )
    with caplog.at_level(logging.INFO, logger="optimus"):
        caplog.clear()  # count only the observation from the request below
        fetched = await main.get_bay_record(created.id, db_session, auth)
    assert fetched.id == created.id  # bay still fully readable in solo mode

    observed = [
        r
        for r in caplog.records
        if getattr(r, "security_event", None) == "authz.capability_observed"
    ]
    # Still exactly one observation per bays request, now recording would_deny.
    assert len(observed) == 1
    assert observed[0].decision == "would_deny"  # type: ignore[attr-defined]


def test_operating_mode_openapi_is_additive_only() -> None:
    schema = main.app.openapi()
    paths = schema["paths"]
    assert "/api/operating-mode/preview" in paths
    assert "/api/operating-mode/apply" in paths
    assert "post" in paths["/api/operating-mode/preview"]
    assert "post" in paths["/api/operating-mode/apply"]
    # Pre-existing surfaces unchanged.
    assert set(paths["/api/bays"].keys()) >= {"get", "post"}
    assert "get" in paths["/api/capabilities"]
