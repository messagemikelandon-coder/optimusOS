from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.db_models as db_models
import app.main as main
from app.auth import AuthContext, get_current_auth_context, hash_password
from app.capability_store import CapabilityStoreError, resolve_capabilities
from app.config import Settings as OwnerSettings
from app.db import get_db_session, get_settings
from app.db_models import AuthSession, Shop, ShopMembership, UserAccount
from app.models import CapabilityId, CapabilityLevel, OperatingMode, SubscriptionTier
from app.shop_store import create_shop_for_new_owner
from tests.test_api import request_for
from tests.test_context_api import create_user
from tests.test_role_isolation import _create_technician

pytestmark = pytest.mark.anyio


def _owner(db: Session) -> UserAccount:
    owner = db.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    return owner


def _auth_for(db: Session, user: UserAccount, suffix: str) -> AuthContext:
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=f"capabilities-{user.id}-{suffix}",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_seen_at=datetime.now(UTC),
    )
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    return AuthContext(user=user, session=auth_session)


def _support_user(db: Session) -> UserAccount:
    user = UserAccount(
        username="capabilities-support",
        display_name="Capabilities Support",
        role="support",
        password_hash=hash_password("support-password-123"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _manager_for(db: Session, owner: UserAccount) -> UserAccount:
    membership = db.scalar(
        select(ShopMembership).where(
            ShopMembership.user_account_id == owner.id,
            ShopMembership.role == "owner",
            ShopMembership.is_active.is_(True),
        )
    )
    assert membership is not None
    manager = UserAccount(
        username="capabilities-manager",
        display_name="Capabilities Manager",
        role="manager",
        shop_owner_id=owner.id,
        password_hash=hash_password("manager-password-123"),
        is_active=True,
    )
    db.add(manager)
    db.flush()
    db.add(ShopMembership(shop_id=membership.shop_id, user_account_id=manager.id, role="manager"))
    db.commit()
    db.refresh(manager)
    return manager


def _set_mode_and_tier(db: Session, owner: UserAccount, *, mode: str, tier: str) -> Shop:
    membership = db.scalar(
        select(ShopMembership).where(
            ShopMembership.user_account_id == owner.id,
            ShopMembership.role == "owner",
            ShopMembership.is_active.is_(True),
        )
    )
    assert membership is not None
    shop = db.get(Shop, membership.shop_id)
    assert shop is not None
    assert shop.subscription is not None
    shop.operating_mode = mode
    shop.subscription.tier = tier
    db.commit()
    db.refresh(shop)
    return shop


# --- resolver matrix -------------------------------------------------------


async def test_new_shop_defaults_to_shop_operating_mode(settings, db_session: Session) -> None:
    owner = UserAccount(
        username="second-owner",
        display_name="Second Owner",
        role="owner",
        password_hash=hash_password("second-owner-pass-123"),
        is_active=True,
    )
    db_session.add(owner)
    db_session.flush()
    shop = create_shop_for_new_owner(db_session, OwnerSettings(), owner, display_name="New Shop")
    db_session.commit()
    db_session.refresh(shop)
    assert shop.operating_mode == "shop"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (
            OperatingMode.SOLO,
            {
                CapabilityId.BAYS: CapabilityLevel.HIDDEN,
                CapabilityId.TECHNICIANS: CapabilityLevel.HIDDEN,
                CapabilityId.SCHEDULING: CapabilityLevel.LIMITED,
                CapabilityId.FIELD_FUNCTIONS: CapabilityLevel.NOT_APPLICABLE,
                CapabilityId.CUSTOMERS: CapabilityLevel.FULL,
            },
        ),
        (
            OperatingMode.MOBILE_FIELD,
            {
                CapabilityId.BAYS: CapabilityLevel.HIDDEN,
                CapabilityId.TECHNICIANS: CapabilityLevel.LIMITED,
                CapabilityId.SCHEDULING: CapabilityLevel.FULL,
                CapabilityId.FIELD_FUNCTIONS: CapabilityLevel.FULL,
                CapabilityId.CUSTOMERS: CapabilityLevel.FULL,
            },
        ),
        (
            OperatingMode.SHOP,
            {
                CapabilityId.BAYS: CapabilityLevel.FULL,
                CapabilityId.TECHNICIANS: CapabilityLevel.FULL,
                CapabilityId.SCHEDULING: CapabilityLevel.FULL,
                CapabilityId.FIELD_FUNCTIONS: CapabilityLevel.LIMITED,
                CapabilityId.CUSTOMERS: CapabilityLevel.FULL,
            },
        ),
    ],
)
async def test_resolver_matches_adr_022_matrix_per_mode_for_owner(
    settings,
    db_session: Session,
    mode: OperatingMode,
    expected: dict[CapabilityId, CapabilityLevel],
) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode=mode.value, tier="shop")
    auth = _auth_for(db_session, owner, f"owner-{mode.value}")

    result = resolve_capabilities(db_session, auth)

    assert result.operating_mode == mode
    levels = {entry.id: entry.level for entry in result.capabilities}
    for capability_id, expected_level in expected.items():
        assert levels[capability_id] == expected_level, (capability_id, mode)
    # Every domain named in the ADR-022 matrix must resolve to something --
    # no silent gaps in the transcription.
    assert set(levels) == set(CapabilityId)


async def test_resolver_uses_the_flat_technician_column_regardless_of_mode(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    tech = _create_technician(db_session, shop_owner_id=owner.id)

    for mode in (OperatingMode.SOLO, OperatingMode.MOBILE_FIELD, OperatingMode.SHOP):
        _set_mode_and_tier(db_session, owner, mode=mode.value, tier="shop")
        db_session.refresh(tech)
        auth = _auth_for(db_session, tech, f"tech-{mode.value}")
        result = resolve_capabilities(db_session, auth)
        levels = {entry.id: entry.level for entry in result.capabilities}
        assert levels[CapabilityId.ESTIMATES] == CapabilityLevel.HIDDEN
        assert levels[CapabilityId.INVOICES] == CapabilityLevel.HIDDEN
        assert levels[CapabilityId.DIAGNOSTICS] == CapabilityLevel.FULL
        assert levels[CapabilityId.TECHNICIANS] == CapabilityLevel.LIMITED
        assert result.role == "technician"


async def test_resolver_reports_tier_and_seats_independent_of_mode(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    shop = _set_mode_and_tier(db_session, owner, mode="solo", tier="team")
    auth = _auth_for(db_session, owner, "tier-check")

    result = resolve_capabilities(db_session, auth)

    assert result.operating_mode == OperatingMode.SOLO
    assert result.tier == SubscriptionTier.TEAM
    assert result.seats_used == 0
    assert shop.subscription is not None
    assert shop.subscription.seat_limit is None or isinstance(shop.subscription.seat_limit, int)


async def test_resolver_output_is_deterministic(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="mobile_field", tier="solo")
    auth = _auth_for(db_session, owner, "determinism")

    first = resolve_capabilities(db_session, auth)
    second = resolve_capabilities(db_session, auth)

    assert [(entry.id, entry.level) for entry in first.capabilities] == [
        (entry.id, entry.level) for entry in second.capabilities
    ]
    assert first.operating_mode == second.operating_mode
    assert first.tier == second.tier
    assert first.role == second.role
    assert first.seat_limit == second.seat_limit
    assert first.seats_used == second.seats_used
    assert first.overrides_applied == second.overrides_applied == []


async def test_resolver_never_raises_to_block_and_adds_no_override_table(
    settings, db_session: Session
) -> None:
    """ADR-022 Decision §5 / this slice's explicit scope: resolution only,
    no enforcement, and overrides are deferred (no storage added)."""
    owner = _owner(db_session)
    auth = _auth_for(db_session, owner, "no-enforcement")
    result = resolve_capabilities(db_session, auth)
    assert result.overrides_applied == []
    # No override table/model exists -- looked up dynamically (not a static
    # import) so this genuinely proves absence at runtime rather than
    # asking pyright to resolve a symbol that must not exist. Matches the
    # goal's explicit "otherwise defer overrides and add no table"
    # instruction.
    assert not hasattr(db_models, "ShopCapabilityOverride")


async def test_resolver_raises_a_clear_error_for_a_shop_with_no_subscription(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    membership = db_session.scalar(
        select(ShopMembership).where(
            ShopMembership.user_account_id == owner.id, ShopMembership.role == "owner"
        )
    )
    assert membership is not None
    shop = db_session.get(Shop, membership.shop_id)
    assert shop is not None
    db_session.delete(shop.subscription)
    db_session.commit()
    # expire_on_commit=False (app/db.py) means `shop` keeps its stale
    # in-memory `.subscription` reference after commit -- force a reload so
    # this test exercises the same "no subscription row" state
    # resolve_capabilities would see from a fresh `db.get()` in production.
    db_session.expire(shop)
    auth = _auth_for(db_session, owner, "no-subscription")
    with pytest.raises(CapabilityStoreError):
        resolve_capabilities(db_session, auth)


# --- tenant isolation --------------------------------------------------


async def test_capabilities_are_isolated_per_shop(settings, db_session: Session) -> None:
    owner_a = _owner(db_session)
    _set_mode_and_tier(db_session, owner_a, mode="solo", tier="solo")

    owner_b = create_user(db_session, username="second-shop-owner", password="second-pass-123")
    _set_mode_and_tier(db_session, owner_b, mode="shop", tier="shop")

    auth_a = _auth_for(db_session, owner_a, "shop-a")
    auth_b = _auth_for(db_session, owner_b, "shop-b")

    result_a = resolve_capabilities(db_session, auth_a)
    result_b = resolve_capabilities(db_session, auth_b)

    assert result_a.operating_mode == OperatingMode.SOLO
    assert result_b.operating_mode == OperatingMode.SHOP
    levels_a = {entry.id: entry.level for entry in result_a.capabilities}
    levels_b = {entry.id: entry.level for entry in result_b.capabilities}
    assert levels_a[CapabilityId.BAYS] == CapabilityLevel.HIDDEN
    assert levels_b[CapabilityId.BAYS] == CapabilityLevel.FULL


# --- endpoint auth (HTTP-level, real dependency injection) -----------------


async def test_capabilities_route_requires_authenticated_session(
    settings, db_session: Session
) -> None:
    with pytest.raises(HTTPException) as excinfo:
        get_current_auth_context(request_for("/api/capabilities"), db_session, settings)
    assert excinfo.value.status_code == 401


def test_capabilities_route_end_to_end_owner_manager_technician_support(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    _create_technician(db_session, shop_owner_id=owner.id)
    _manager_for(db_session, owner)
    _support_user(db_session)

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)

        unauth = client.get("/api/capabilities")
        assert unauth.status_code == 401

        owner_login = client.post(
            "/api/auth/login", json={"username": "owner", "password": "owner-password-123"}
        )
        assert owner_login.status_code == 200
        owner_response = client.get("/api/capabilities")
        assert owner_response.status_code == 200
        body = owner_response.json()
        assert body["operating_mode"] in {"solo", "mobile_field", "shop"}
        assert body["tier"] in {"solo", "team", "shop"}
        assert body["role"] == "owner"
        assert len(body["capabilities"]) == len(CapabilityId)
        # No secrets/provider data leak through this read-only surface.
        forbidden_substrings = ("square", "token", "password", "secret", "api_key")
        serialized = str(body).lower()
        for needle in forbidden_substrings:
            assert needle not in serialized, needle
        client.post("/api/auth/logout")

        manager_login = client.post(
            "/api/auth/login",
            json={"username": "capabilities-manager", "password": "manager-password-123"},
        )
        assert manager_login.status_code == 200
        assert client.get("/api/capabilities").status_code == 200
        client.post("/api/auth/logout")

        tech_login = client.post(
            "/api/auth/login", json={"username": "tech-one", "password": "tech-password-123"}
        )
        assert tech_login.status_code == 200
        assert client.get("/api/capabilities").status_code == 403
        client.post("/api/auth/logout")

        support_login = client.post(
            "/api/auth/login",
            json={"username": "capabilities-support", "password": "support-password-123"},
        )
        assert support_login.status_code == 200
        assert client.get("/api/capabilities").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


# --- no unintended route/OpenAPI change -------------------------------


def test_capabilities_is_additive_and_existing_routes_are_unchanged() -> None:
    schema = main.app.openapi()
    assert "/api/capabilities" in schema["paths"]
    assert "get" in schema["paths"]["/api/capabilities"]
    # Spot-check a representative sample of pre-existing route groups
    # (one per module classification in the bridge doc) to catch an
    # accidental path/method change, without re-asserting this file's
    # entire route table (already exhaustively covered by
    # tests/test_role_isolation.py::test_every_business_route_is_role_gated_as_expected).
    for path, methods in (
        ("/api/technicians", {"get", "post"}),
        ("/api/billing/subscription", {"get"}),
        ("/api/bays", {"get", "post"}),
        ("/api/appointments", {"get", "post"}),
        ("/api/customers", {"get", "post"}),
    ):
        assert path in schema["paths"], path
        assert methods <= set(schema["paths"][path].keys()), path


def test_shop_operating_mode_check_constraint_rejects_an_invalid_value(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    membership = db_session.scalar(
        select(ShopMembership).where(
            ShopMembership.user_account_id == owner.id, ShopMembership.role == "owner"
        )
    )
    assert membership is not None
    shop = db_session.get(Shop, membership.shop_id)
    assert shop is not None
    shop.operating_mode = "not_a_real_mode"
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
