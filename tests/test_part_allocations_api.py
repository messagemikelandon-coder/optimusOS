from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.main as main
from app.models import (
    EstimatePaymentOptionCode,
    PartAllocationAllocateRequest,
    PartAllocationCreate,
    PartAllocationRead,
    PartAllocationReturnRequest,
    PartAllocationUseRequest,
    TechnicianCreate,
    TechnicianProvisionLoginRequest,
    WorkOrderAssignTechnicianRequest,
)
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_diagnostics_and_inspections_api import _create_technician_with_assigned_work_order
from tests.test_vendors_and_parts_api import part_payload, vendor_payload
from tests.test_work_orders_api import create_approved_estimate_for_auth


async def _create_second_technician_with_assigned_work_order(
    monkeypatch, settings, db_session: Session, owner_auth
):
    """A second, distinct technician (the shared helper's username is
    hardcoded, so it can't be called twice in one test) assigned to their
    own separate work order, for cross-technician isolation testing."""
    work_order, _part = await _create_work_order_and_part(
        monkeypatch, settings, db_session, owner_auth, vin="1FTFW1ET1EFA00088"
    )
    technician = await main.create_technician_record(
        TechnicianCreate(first_name="Alex", last_name="Chen", employment_status="Full-time"),
        db_session,
        owner_auth,
    )
    await main.provision_technician_login_record(
        technician.id,
        TechnicianProvisionLoginRequest(username="alex.chen", password="tech-login-pass-456"),
        db_session,
        owner_auth,
    )
    _, login_response = await login_as(
        settings, db_session, username="alex.chen", password="tech-login-pass-456"
    )
    technician_auth = auth_context(settings, db_session, raw_cookie_from_response(login_response))
    await main.assign_work_order_technician_record(
        work_order.id,
        WorkOrderAssignTechnicianRequest(technician_id=technician.id),
        db_session,
        owner_auth,
    )
    return technician_auth, work_order


pytestmark = pytest.mark.anyio


async def _create_work_order_and_part(
    monkeypatch, settings, db_session: Session, auth, *, vin: str | None = None
):
    vendor = await main.create_vendor_record(vendor_payload(), db_session, auth)
    part = await main.create_part_record(
        part_payload(vendor_id=vendor.id, quantity_on_hand=10), db_session, auth
    )
    vehicle_overrides = {"vin": vin} if vin else {}
    _, estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
        **vehicle_overrides,
    )
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)
    return work_order, part


async def test_part_allocations_require_authenticated_session(
    settings, db_session: Session
) -> None:
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(
            request_for("/api/work-orders/1/part-allocations"), db_session, settings
        )
    assert excinfo.value.status_code == 401


async def test_create_and_list_part_allocation_snapshots_unit_cost(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    work_order, part = await _create_work_order_and_part(monkeypatch, settings, db_session, auth)

    created = await main.create_part_allocation_record(
        work_order.id,
        PartAllocationCreate(part_id=part.id, quantity_required=3),
        db_session,
        auth,
    )
    assert created.quantity_required == 3
    assert created.quantity_allocated == 0
    assert isinstance(created, PartAllocationRead)  # owner session: full read, cost included
    assert created.unit_cost_snapshot == part.unit_cost

    listed = await main.list_part_allocation_records(work_order.id, db_session, auth)
    assert [item.id for item in listed.items] == [created.id]


async def test_allocate_deducts_inventory_and_rejects_insufficient_stock(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    work_order, part = await _create_work_order_and_part(monkeypatch, settings, db_session, auth)
    allocation = await main.create_part_allocation_record(
        work_order.id, PartAllocationCreate(part_id=part.id, quantity_required=8), db_session, auth
    )

    allocated = await main.allocate_part_record(
        allocation.id, PartAllocationAllocateRequest(quantity=6), db_session, auth
    )
    assert allocated.quantity_allocated == 6
    part_after = await main.get_part_record(part.id, db_session, auth)
    assert part_after.quantity_on_hand == 4

    # Only 4 remain -- requesting 6 more without an override must be rejected
    # outright, not silently clamped.
    with pytest.raises(HTTPException) as excinfo:
        await main.allocate_part_record(
            allocation.id, PartAllocationAllocateRequest(quantity=6), db_session, auth
        )
    assert excinfo.value.status_code == 422
    part_unchanged = await main.get_part_record(part.id, db_session, auth)
    assert part_unchanged.quantity_on_hand == 4


async def test_allocate_override_requires_a_reason_and_clamps_to_zero(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    work_order, part = await _create_work_order_and_part(monkeypatch, settings, db_session, auth)
    allocation = await main.create_part_allocation_record(
        work_order.id, PartAllocationCreate(part_id=part.id, quantity_required=20), db_session, auth
    )

    # Override checked but no reason given -- rejected.
    with pytest.raises(HTTPException) as excinfo:
        await main.allocate_part_record(
            allocation.id,
            PartAllocationAllocateRequest(quantity=15, override=True),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422

    # Override with a reason -- succeeds, and Part.quantity_on_hand is
    # clamped to zero, never negative (the pre-existing CHECK constraint on
    # Part.quantity_on_hand is never violated, by design).
    overridden = await main.allocate_part_record(
        allocation.id,
        PartAllocationAllocateRequest(
            quantity=15, override=True, override_reason="Borrowing from another job"
        ),
        db_session,
        auth,
    )
    assert overridden.quantity_allocated == 15
    part_after = await main.get_part_record(part.id, db_session, auth)
    assert part_after.quantity_on_hand == 0

    events = await main.list_part_allocation_event_records(allocation.id, db_session, auth)
    allocated_event = next(e for e in events.events if e.event_type == "allocated")
    assert allocated_event.inventory_override is True
    assert allocated_event.override_reason == "Borrowing from another job"


async def test_use_and_return_are_bounded_by_allocated_quantity(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    work_order, part = await _create_work_order_and_part(monkeypatch, settings, db_session, auth)
    allocation = await main.create_part_allocation_record(
        work_order.id, PartAllocationCreate(part_id=part.id, quantity_required=5), db_session, auth
    )
    await main.allocate_part_record(
        allocation.id, PartAllocationAllocateRequest(quantity=5), db_session, auth
    )

    # Cannot mark more used than allocated.
    with pytest.raises(HTTPException) as use_exc:
        await main.use_part_allocation_record(
            allocation.id, PartAllocationUseRequest(quantity=6), db_session, auth
        )
    assert use_exc.value.status_code == 422

    used = await main.use_part_allocation_record(
        allocation.id, PartAllocationUseRequest(quantity=3), db_session, auth
    )
    assert used.quantity_used == 3

    # Cannot return more than allocated-but-unused (5 allocated - 3 used = 2
    # returnable).
    with pytest.raises(HTTPException) as return_exc:
        await main.return_part_allocation_record(
            allocation.id, PartAllocationReturnRequest(quantity=3), db_session, auth
        )
    assert return_exc.value.status_code == 422

    returned = await main.return_part_allocation_record(
        allocation.id, PartAllocationReturnRequest(quantity=2), db_session, auth
    )
    assert returned.quantity_returned == 2
    part_after = await main.get_part_record(part.id, db_session, auth)
    # started at 10, allocate 5 -> 5, return 2 -> 7
    assert part_after.quantity_on_hand == 7


async def test_part_allocation_cross_owner_isolation(
    monkeypatch, settings, db_session: Session
) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    work_order, part = await _create_work_order_and_part(
        monkeypatch, settings, db_session, owner_auth
    )
    allocation = await main.create_part_allocation_record(
        work_order.id,
        PartAllocationCreate(part_id=part.id, quantity_required=2),
        db_session,
        owner_auth,
    )

    with pytest.raises(HTTPException) as get_exc:
        await main.get_part_allocation_record(allocation.id, db_session, other_auth)
    assert get_exc.value.status_code == 404

    with pytest.raises(HTTPException) as list_exc:
        await main.list_part_allocation_records(work_order.id, db_session, other_auth)
    assert list_exc.value.status_code == 422


async def test_technician_can_create_and_allocate_parts_on_own_assigned_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    technician_auth, work_order, _vehicle = await _create_technician_with_assigned_work_order(
        monkeypatch, settings, db_session, owner_auth
    )
    vendor = await main.create_vendor_record(vendor_payload(), db_session, owner_auth)
    part = await main.create_part_record(
        part_payload(vendor_id=vendor.id, quantity_on_hand=10), db_session, owner_auth
    )

    created = await main.create_part_allocation_record(
        work_order.id,
        PartAllocationCreate(part_id=part.id, quantity_required=4),
        db_session,
        technician_auth,
    )
    allocated = await main.allocate_part_record(
        created.id, PartAllocationAllocateRequest(quantity=4), db_session, technician_auth
    )
    assert allocated.quantity_allocated == 4

    # The owner can see it too.
    owner_fetched = await main.get_part_allocation_record(created.id, db_session, owner_auth)
    assert owner_fetched.id == created.id


async def test_technician_part_allocation_response_excludes_unit_cost_snapshot(
    monkeypatch, settings, db_session: Session
) -> None:
    """`unit_cost_snapshot` is an internal cost-basis field that feeds the
    owner's Gross Profit calculation -- a technician's own view of a part
    allocation must not expose it, same reasoning as `TechnicianSelfRead`
    omitting `hourly_cost`. Found by an `optimus-security-reviewer` pass
    (2026-07-17); this test pins the fix."""
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    technician_auth, work_order, _vehicle = await _create_technician_with_assigned_work_order(
        monkeypatch, settings, db_session, owner_auth
    )
    vendor = await main.create_vendor_record(vendor_payload(), db_session, owner_auth)
    part = await main.create_part_record(
        part_payload(vendor_id=vendor.id, quantity_on_hand=10, unit_cost=42.5),
        db_session,
        owner_auth,
    )

    created = await main.create_part_allocation_record(
        work_order.id,
        PartAllocationCreate(part_id=part.id, quantity_required=1),
        db_session,
        technician_auth,
    )
    assert "unit_cost_snapshot" not in type(created).model_fields

    owner_fetched = await main.get_part_allocation_record(created.id, db_session, owner_auth)
    assert isinstance(owner_fetched, PartAllocationRead)  # owner session: full read, cost included
    assert owner_fetched.unit_cost_snapshot == 42.5

    listed = await main.list_part_allocation_records(work_order.id, db_session, technician_auth)
    assert "unit_cost_snapshot" not in type(listed.items[0]).model_fields


def test_technician_part_allocation_wire_response_omits_unit_cost_snapshot_key(
    monkeypatch, settings, db_session: Session
) -> None:
    """Real HTTP through the actual FastAPI dependency graph, not a direct
    handler call -- proves the `PartAllocationRead | PartAllocationTechnicianRead`
    `response_model` union actually omits `unit_cost_snapshot` from the JSON
    body for a technician session rather than serializing it as `null`
    (FastAPI/Pydantic union serialization behavior, not just a Python-object
    type check). Companion to
    `test_technician_part_allocation_response_excludes_unit_cost_snapshot`,
    which proves the store returns the narrower model but not what actually
    lands on the wire."""
    import asyncio

    from fastapi.testclient import TestClient

    from app.db import get_db_session, get_settings

    async def _seed() -> tuple[int, int]:
        _, owner_response = await login_as(settings, db_session)
        owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
        _technician_auth, work_order, _vehicle = await _create_technician_with_assigned_work_order(
            monkeypatch, settings, db_session, owner_auth
        )
        vendor = await main.create_vendor_record(vendor_payload(), db_session, owner_auth)
        part = await main.create_part_record(
            part_payload(vendor_id=vendor.id, quantity_on_hand=10, unit_cost=42.5),
            db_session,
            owner_auth,
        )
        allocation = await main.create_part_allocation_record(
            work_order.id,
            PartAllocationCreate(part_id=part.id, quantity_required=1),
            db_session,
            owner_auth,
        )
        return allocation.id, work_order.id

    allocation_id, work_order_id = asyncio.run(_seed())

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        tech_login = client.post(
            "/api/auth/login",
            json={"username": "jordan.reyes", "password": "tech-login-pass-123"},
        )
        assert tech_login.status_code == 200
        assert tech_login.json()["user"]["role"] == "technician"

        get_response = client.get(f"/api/part-allocations/{allocation_id}")
        assert get_response.status_code == 200
        assert "unit_cost_snapshot" not in get_response.json()

        list_response = client.get(f"/api/work-orders/{work_order_id}/part-allocations")
        assert list_response.status_code == 200
        assert "unit_cost_snapshot" not in list_response.json()["items"][0]
        client.post("/api/auth/logout")

        owner_login = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner-password-123"},
        )
        assert owner_login.status_code == 200
        owner_get = client.get(f"/api/part-allocations/{allocation_id}")
        assert owner_get.status_code == 200
        assert owner_get.json()["unit_cost_snapshot"] == 42.5
    finally:
        main.app.dependency_overrides.clear()


async def test_technician_cannot_access_allocations_on_an_unassigned_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    technician_auth, _assigned_wo, _vehicle = await _create_technician_with_assigned_work_order(
        monkeypatch, settings, db_session, owner_auth
    )
    other_work_order, part = await _create_work_order_and_part(
        monkeypatch, settings, db_session, owner_auth, vin="1FTFW1ET1EFA00099"
    )
    allocation = await main.create_part_allocation_record(
        other_work_order.id,
        PartAllocationCreate(part_id=part.id, quantity_required=1),
        db_session,
        owner_auth,
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.get_part_allocation_record(allocation.id, db_session, technician_auth)
    assert excinfo.value.status_code == 404


async def test_part_allocation_events_track_allocate_use_return(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    work_order, part = await _create_work_order_and_part(monkeypatch, settings, db_session, auth)
    allocation = await main.create_part_allocation_record(
        work_order.id, PartAllocationCreate(part_id=part.id, quantity_required=5), db_session, auth
    )
    await main.allocate_part_record(
        allocation.id, PartAllocationAllocateRequest(quantity=5), db_session, auth
    )
    await main.use_part_allocation_record(
        allocation.id, PartAllocationUseRequest(quantity=2), db_session, auth
    )
    await main.return_part_allocation_record(
        allocation.id, PartAllocationReturnRequest(quantity=1), db_session, auth
    )

    events = await main.list_part_allocation_event_records(allocation.id, db_session, auth)
    assert [e.event_type for e in events.events] == ["allocated", "used", "returned"]
    assert [e.quantity_delta for e in events.events] == [5, 2, 1]
    for event in events.events:
        assert event.actor_type == "owner"
        assert event.actor_name == "Owner"


async def test_technician_cannot_access_a_different_technicians_assigned_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    """Stronger than the unassigned-work-order case above: technician A's
    own scoping must exclude technician B's allocations even though both
    are real, assigned technicians on the same shop -- not just "assigned
    to nobody"."""
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    (
        technician_a_auth,
        _work_order_a,
        _vehicle_a,
    ) = await _create_technician_with_assigned_work_order(
        monkeypatch, settings, db_session, owner_auth
    )
    technician_b_auth, work_order_b = await _create_second_technician_with_assigned_work_order(
        monkeypatch, settings, db_session, owner_auth
    )
    vendor = await main.create_vendor_record(vendor_payload(), db_session, owner_auth)
    part = await main.create_part_record(
        part_payload(vendor_id=vendor.id, quantity_on_hand=10), db_session, owner_auth
    )
    allocation_b = await main.create_part_allocation_record(
        work_order_b.id,
        PartAllocationCreate(part_id=part.id, quantity_required=2),
        db_session,
        technician_b_auth,
    )

    with pytest.raises(HTTPException) as get_exc:
        await main.get_part_allocation_record(allocation_b.id, db_session, technician_a_auth)
    assert get_exc.value.status_code == 404

    with pytest.raises(HTTPException) as allocate_exc:
        await main.allocate_part_record(
            allocation_b.id,
            PartAllocationAllocateRequest(quantity=1),
            db_session,
            technician_a_auth,
        )
    assert allocate_exc.value.status_code == 404
