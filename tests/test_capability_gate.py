from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability_gate import (
    CapabilityDecision,
    CapabilityGateMode,
    evaluate_capability,
)
from app.db_models import Shop, ShopMembership
from app.models import CapabilityId, CapabilityLevel
from app.security_events import SecurityEventType
from tests.test_capabilities_api import _auth_for, _owner, _set_mode_and_tier

pytestmark = pytest.mark.anyio

_OBSERVED = f"security event: {SecurityEventType.CAPABILITY_OBSERVED.value}"


def _capability_records(caplog) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "security_event", None) == SecurityEventType.CAPABILITY_OBSERVED.value
    ]


def _field(record: logging.LogRecord, name: str):
    """Read a structured log-record field. LogRecord carries these via
    `extra=`, so they are dynamic attributes pyright cannot see statically --
    this getattr indirection keeps the assertions type-clean, matching how
    the emitter flattens the event's metadata onto the record."""
    return getattr(record, name)


# --- OBSERVE mode: never changes behavior, records the would-be decision ---


async def test_observe_shop_mode_bays_would_allow(settings, db_session: Session, caplog) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "observe-shop")

    with caplog.at_level(logging.INFO, logger="optimus"):
        observation = await _run(db_session, auth)

    assert observation.decision is CapabilityDecision.WOULD_ALLOW
    assert observation.level is CapabilityLevel.FULL
    assert observation.mode is CapabilityGateMode.OBSERVE


@pytest.mark.parametrize("mode", ["solo", "mobile_field"])
async def test_observe_non_shop_mode_bays_would_deny_but_still_allows(
    settings, db_session: Session, caplog, mode: str
) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode=mode, tier="shop")
    auth = _auth_for(db_session, owner, f"observe-{mode}")

    with caplog.at_level(logging.INFO, logger="optimus"):
        observation = await _run(db_session, auth)

    # would_deny is *recorded*, but OBSERVE returns normally -- it never
    # raises, so the caller (the bay handler) proceeds unchanged.
    assert observation.decision is CapabilityDecision.WOULD_DENY
    assert observation.level is CapabilityLevel.HIDDEN


async def test_observe_emits_exactly_one_event_per_call(
    settings, db_session: Session, caplog
) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="team")
    auth = _auth_for(db_session, owner, "observe-one-event")

    with caplog.at_level(logging.INFO, logger="optimus"):
        await _run(db_session, auth)

    records = _capability_records(caplog)
    assert len(records) == 1
    assert _OBSERVED in caplog.text


async def test_observe_event_carries_the_required_non_secret_telemetry(
    settings, db_session: Session, caplog
) -> None:
    owner = _owner(db_session)
    shop = _set_mode_and_tier(db_session, owner, mode="solo", tier="team")
    auth = _auth_for(db_session, owner, "observe-telemetry")

    with caplog.at_level(logging.INFO, logger="optimus"):
        await _run(db_session, auth)

    record = _capability_records(caplog)[-1]
    # Every required telemetry field, present and correct.
    assert _field(record, "shop_id") == shop.id
    assert _field(record, "actor_role") == "owner"
    assert _field(record, "gate_mode") == "observe"
    assert _field(record, "operating_mode") == "solo"
    assert _field(record, "tier") == "team"
    assert _field(record, "capability") == CapabilityId.BAYS.value
    assert _field(record, "capability_level") == "hidden"
    assert _field(record, "decision") == "would_deny"
    assert _field(record, "route_action") == "bays.list"
    assert hasattr(record, "occurred_at")
    assert _field(record, "actor_type") == "user"


async def test_observe_event_contains_no_secret_shaped_values(
    settings, db_session: Session, caplog
) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "observe-no-secret")

    with caplog.at_level(logging.INFO, logger="optimus"):
        await _run(db_session, auth)

    record = _capability_records(caplog)[-1]
    rendered = " ".join(f"{k}={v}" for k, v in record.__dict__.items()).lower()
    for forbidden in ("password", "secret", "token", "api_key", "square"):
        assert forbidden not in rendered, forbidden


# --- OBSERVE resolution failure: fails open, records resolution_error -------


async def test_observe_fails_open_on_resolution_failure(
    settings, db_session: Session, caplog
) -> None:
    owner = _owner(db_session)
    membership = db_session.scalar(
        select(ShopMembership).where(
            ShopMembership.user_account_id == owner.id, ShopMembership.role == "owner"
        )
    )
    assert membership is not None
    shop = db_session.get(Shop, membership.shop_id)
    assert shop is not None and shop.subscription is not None
    db_session.delete(shop.subscription)
    db_session.commit()
    db_session.expire(shop)
    auth = _auth_for(db_session, owner, "observe-resolution-error")

    with caplog.at_level(logging.INFO, logger="optimus"):
        # Fails open: returns normally (does not raise) despite the failure.
        observation = await _run(db_session, auth)

    assert observation.decision is CapabilityDecision.RESOLUTION_ERROR
    assert observation.level is None
    record = _capability_records(caplog)[-1]
    assert _field(record, "decision") == "resolution_error"
    assert _field(record, "result") == "failure"
    # shop_id is still emitted (membership resolves even when subscription does not).
    assert _field(record, "shop_id") == membership.shop_id


# --- ENFORCE mode: real deny path, unit-tested here only (no route uses it) -


async def test_enforce_allows_available_capability(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    auth = _auth_for(db_session, owner, "enforce-allow")

    observation = evaluate_capability(
        db_session,
        auth,
        CapabilityId.BAYS,
        action="bays.list",
        mode=CapabilityGateMode.ENFORCE,
    )
    assert observation.decision is CapabilityDecision.WOULD_ALLOW


@pytest.mark.parametrize("mode", ["solo", "mobile_field"])
async def test_enforce_denies_unavailable_capability(
    settings, db_session: Session, mode: str
) -> None:
    owner = _owner(db_session)
    _set_mode_and_tier(db_session, owner, mode=mode, tier="shop")
    auth = _auth_for(db_session, owner, f"enforce-deny-{mode}")

    with pytest.raises(HTTPException) as excinfo:
        evaluate_capability(
            db_session,
            auth,
            CapabilityId.BAYS,
            action="bays.list",
            mode=CapabilityGateMode.ENFORCE,
        )
    assert excinfo.value.status_code == 403


async def test_enforce_fails_closed_on_resolution_failure(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    membership = db_session.scalar(
        select(ShopMembership).where(
            ShopMembership.user_account_id == owner.id, ShopMembership.role == "owner"
        )
    )
    assert membership is not None
    shop = db_session.get(Shop, membership.shop_id)
    assert shop is not None and shop.subscription is not None
    db_session.delete(shop.subscription)
    db_session.commit()
    db_session.expire(shop)
    auth = _auth_for(db_session, owner, "enforce-fail-closed")

    with pytest.raises(HTTPException) as excinfo:
        evaluate_capability(
            db_session,
            auth,
            CapabilityId.BAYS,
            action="bays.list",
            mode=CapabilityGateMode.ENFORCE,
        )
    assert excinfo.value.status_code == 403


async def _run(db_session: Session, auth):
    """Runs the gate exactly as the bays router does: OBSERVE mode, one call."""
    import asyncio

    return await asyncio.to_thread(
        evaluate_capability,
        db_session,
        auth,
        CapabilityId.BAYS,
        action="bays.list",
        mode=CapabilityGateMode.OBSERVE,
    )
