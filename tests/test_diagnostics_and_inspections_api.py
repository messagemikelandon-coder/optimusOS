from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.main as main
from app.models import (
    CustomerCreate,
    DiagnosticFindingCreate,
    DiagnosticFindingUpdate,
    EstimatePaymentOptionCode,
    InspectionCreate,
    InspectionItem,
    InspectionUpdate,
    VehicleCreate,
    VehicleRead,
)
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_work_orders_api import create_approved_estimate_for_auth

pytestmark = pytest.mark.anyio


async def _create_vehicle(settings, db_session: Session, auth) -> VehicleRead:
    customer = await main.create_customer_record(
        CustomerCreate(first_name="Sample", last_name="Customer"), db_session, auth
    )
    return await main.create_vehicle_record(
        customer.id,
        VehicleCreate(year=2018, make="Honda", model="Civic"),
        db_session,
        auth,
    )


async def test_diagnostic_findings_require_authenticated_session(
    settings, db_session: Session
) -> None:
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/diagnostic-findings"), db_session, settings)
    assert excinfo.value.status_code == 401


async def test_create_and_update_diagnostic_finding(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(
            vehicle_id=vehicle.id,
            codes="P0301",
            symptoms="Rough idle at startup.",
        ),
        db_session,
        auth,
    )
    assert created.vehicle_display_name == vehicle.display_name
    assert created.codes == "P0301"

    updated = await main.update_diagnostic_finding_record(
        created.id,
        DiagnosticFindingUpdate(conclusion="Replaced ignition coil #3."),
        db_session,
        auth,
    )
    assert updated.conclusion == "Replaced ignition coil #3."
    assert updated.symptoms == "Rough idle at startup."


async def test_diagnostic_finding_rejects_unknown_vehicle(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    with pytest.raises(HTTPException) as excinfo:
        await main.create_diagnostic_finding_record(
            DiagnosticFindingCreate(vehicle_id=999999, symptoms="Test"), db_session, auth
        )
    assert excinfo.value.status_code == 422


async def test_diagnostic_finding_cross_owner_isolation(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    vehicle = await _create_vehicle(settings, db_session, owner_auth)

    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Test"), db_session, owner_auth
    )

    # A second owner cannot even reference the first owner's vehicle.
    with pytest.raises(HTTPException) as create_exc:
        await main.create_diagnostic_finding_record(
            DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Test"),
            db_session,
            other_auth,
        )
    assert create_exc.value.status_code == 422

    with pytest.raises(HTTPException) as get_exc:
        await main.get_diagnostic_finding_record(created.id, db_session, other_auth)
    assert get_exc.value.status_code == 404


async def test_delete_diagnostic_finding(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)
    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Test"), db_session, auth
    )

    await main.delete_diagnostic_finding_record(created.id, db_session, auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.get_diagnostic_finding_record(created.id, db_session, auth)
    assert excinfo.value.status_code == 404


async def test_create_and_update_inspection_with_items(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    created = await main.create_inspection_record(
        InspectionCreate(
            vehicle_id=vehicle.id,
            inspection_type="Multi-point",
            items=[
                InspectionItem(label="Brake pads", status="ok"),
                InspectionItem(label="Tire tread", status="attention", note="4/32 remaining"),
            ],
        ),
        db_session,
        auth,
    )
    assert len(created.items) == 2
    assert created.has_attention_items is True
    assert created.has_failed_items is False

    updated = await main.update_inspection_record(
        created.id,
        InspectionUpdate(
            items=[
                InspectionItem(label="Brake pads", status="fail", note="Below minimum"),
            ]
        ),
        db_session,
        auth,
    )
    assert len(updated.items) == 1
    assert updated.has_failed_items is True
    assert updated.has_attention_items is False


async def test_inspection_cross_owner_isolation(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    vehicle = await _create_vehicle(settings, db_session, owner_auth)

    created = await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id), db_session, owner_auth
    )

    other_list = await main.list_inspection_records(
        db_session,
        settings,
        other_auth,
        page=1,
        page_size=20,
        vehicle_id=None,
        work_order_id=None,
    )
    assert other_list.items == []

    with pytest.raises(HTTPException) as excinfo:
        await main.get_inspection_record(created.id, db_session, other_auth)
    assert excinfo.value.status_code == 404


async def test_delete_inspection(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)
    created = await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id), db_session, auth
    )

    await main.delete_inspection_record(created.id, db_session, auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.get_inspection_record(created.id, db_session, auth)
    assert excinfo.value.status_code == 404


async def test_diagnostic_finding_rejects_cross_owner_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    """Regression test for an independent-review finding: vehicle_id and
    technician_id were validated against the caller's own owner scope, but
    work_order_id was written straight through with no ownership check --
    a real cross-tenant write-path isolation gap on a field the DB-level FK
    alone can't catch (it only proves the row exists, not who owns it)."""
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    _, owner_estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        owner_auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
    )
    owner_work_order = await main.create_work_order_record(
        owner_estimate.id, db_session, owner_auth
    )
    other_vehicle = await _create_vehicle(settings, db_session, other_auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_diagnostic_finding_record(
            DiagnosticFindingCreate(
                vehicle_id=other_vehicle.id,
                work_order_id=owner_work_order.id,
                symptoms="Test",
            ),
            db_session,
            other_auth,
        )
    assert excinfo.value.status_code == 422


async def test_inspection_rejects_cross_owner_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    _, owner_estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        owner_auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
    )
    owner_work_order = await main.create_work_order_record(
        owner_estimate.id, db_session, owner_auth
    )
    other_vehicle = await _create_vehicle(settings, db_session, other_auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_inspection_record(
            InspectionCreate(vehicle_id=other_vehicle.id, work_order_id=owner_work_order.id),
            db_session,
            other_auth,
        )
    assert excinfo.value.status_code == 422
