from __future__ import annotations

from typing import TypedDict, Unpack

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.main as main
from app.models import (
    IntakeRequestConvertRequest,
    IntakeRequestCreate,
    IntakeRequestUpdate,
    IntakeStatus,
)
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response

pytestmark = pytest.mark.anyio


class IntakePayload(TypedDict, total=False):
    customer_name: str
    phone: str | None
    email: str | None
    vehicle_description: str | None
    complaint: str


def intake_payload(**overrides: Unpack[IntakePayload]) -> IntakeRequestCreate:
    base: IntakePayload = {
        "customer_name": "Jordan Reyes",
        "phone": "(555) 987-6543",
        "email": "Jordan.Reyes@example.com",
        "vehicle_description": "2018 Honda Civic",
        "complaint": "Grinding noise when braking.",
    }
    base.update(overrides)
    return IntakeRequestCreate(**base)


async def test_intake_requests_require_authenticated_session(settings, db_session: Session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/intake-requests"), db_session, settings)
    assert excinfo.value.status_code == 401


async def test_create_and_update_intake_request(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    created = await main.create_intake_request_record(intake_payload(), db_session, auth)
    assert created.status == IntakeStatus.NEW
    assert created.email == "jordan.reyes@example.com"

    updated = await main.update_intake_request_record(
        created.id,
        IntakeRequestUpdate(status=IntakeStatus.CONTACTED),
        db_session,
        auth,
    )
    assert updated.status == IntakeStatus.CONTACTED


async def test_intake_request_cross_owner_isolation(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    created = await main.create_intake_request_record(intake_payload(), db_session, owner_auth)

    other_list = await main.list_intake_request_records(
        db_session, settings, other_auth, page=1, page_size=20, search=None, status_filter=None
    )
    assert other_list.items == []

    with pytest.raises(HTTPException) as excinfo:
        await main.get_intake_request_record(created.id, db_session, other_auth)
    assert excinfo.value.status_code == 404


async def test_convert_intake_request_creates_customer_and_vehicle(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_intake_request_record(intake_payload(), db_session, auth)

    result = await main.convert_intake_request_record(
        created.id,
        IntakeRequestConvertRequest(vehicle_year=2018, vehicle_make="Honda", vehicle_model="Civic"),
        db_session,
        auth,
    )
    assert result.customer.first_name == "Jordan"
    assert result.customer.last_name == "Reyes"
    assert result.customer.email == "jordan.reyes@example.com"
    assert result.vehicle is not None
    assert result.vehicle.make == "Honda"
    assert result.intake_request.status == IntakeStatus.CONVERTED
    assert result.intake_request.converted_customer_id == result.customer.id
    assert result.intake_request.converted_vehicle_id == result.vehicle.id

    fetched_customer = await main.get_customer_record(result.customer.id, db_session, auth)
    assert fetched_customer.id == result.customer.id


async def test_convert_without_vehicle_details_creates_customer_only(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_intake_request_record(
        intake_payload(customer_name="Solo Customer"), db_session, auth
    )

    result = await main.convert_intake_request_record(
        created.id, IntakeRequestConvertRequest(), db_session, auth
    )
    assert result.vehicle is None
    assert result.intake_request.converted_vehicle_id is None


async def test_convert_twice_is_rejected(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_intake_request_record(intake_payload(), db_session, auth)
    await main.convert_intake_request_record(
        created.id, IntakeRequestConvertRequest(), db_session, auth
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.convert_intake_request_record(
            created.id, IntakeRequestConvertRequest(), db_session, auth
        )
    assert excinfo.value.status_code == 409


async def test_converted_status_cannot_be_hand_edited(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_intake_request_record(intake_payload(), db_session, auth)
    await main.convert_intake_request_record(
        created.id, IntakeRequestConvertRequest(), db_session, auth
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.update_intake_request_record(
            created.id, IntakeRequestUpdate(status=IntakeStatus.NEW), db_session, auth
        )
    assert excinfo.value.status_code == 409
