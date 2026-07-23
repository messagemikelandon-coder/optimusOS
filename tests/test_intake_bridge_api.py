from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main as main
from app.db_models import Customer, Vehicle
from app.models import (
    CustomerCreate,
    IntakeRequestConvertRequest,
    IntakeRequestCreate,
    IntakeRequestUpdate,
    VehicleCreate,
)
from tests.test_context_api import (
    auth_context,
    create_user,
    login_as,
    raw_cookie_from_response,
)

pytestmark = pytest.mark.anyio


async def _owner_auth(settings, db_session: Session):
    _, response = await login_as(settings, db_session)
    return auth_context(settings, db_session, raw_cookie_from_response(response))


async def _create_draft(db_session: Session, auth, **overrides: object):
    payload: dict[str, object] = {
        "customer_name": "Jordan Reyes",
        "complaint": "Grinding noise when braking.",
    }
    payload.update(overrides)
    return await main.create_intake_request_record(
        IntakeRequestCreate.model_validate(payload), db_session, auth
    )


async def test_draft_holds_vin_decoded_vehicle_before_customer(
    settings, db_session: Session
) -> None:
    # A draft can carry structured VIN-decoded vehicle data with no customer or
    # canonical vehicle in existence yet.
    auth = await _owner_auth(settings, db_session)
    draft = await _create_draft(
        db_session,
        auth,
        vehicle_vin="1HGFA16588L000000",
        vehicle_year=2018,
        vehicle_make="Honda",
        vehicle_model="Civic",
        vehicle_trim="EX",
        vehicle_engine="1.5L Turbo",
        vehicle_drivetrain="FWD",
    )
    assert draft.vehicle_vin == "1HGFA16588L000000"
    assert draft.vehicle_make == "Honda"
    assert draft.converted_customer_id is None
    # No customer or vehicle rows were created by drafting.
    assert db_session.scalar(select(func.count()).select_from(Customer)) == 0
    assert db_session.scalar(select(func.count()).select_from(Vehicle)) == 0


async def test_convert_uses_stored_vehicle_fields(settings, db_session: Session) -> None:
    # Conversion defaults the vehicle from the draft's stored fields, so a shop
    # that decoded a VIN at intake need not re-enter it.
    auth = await _owner_auth(settings, db_session)
    draft = await _create_draft(
        db_session,
        auth,
        vehicle_vin="1HGFA16588L000001",
        vehicle_year=2018,
        vehicle_make="Honda",
        vehicle_model="Civic",
    )
    result = await main.convert_intake_request_record(
        draft.id, IntakeRequestConvertRequest(), db_session, auth
    )
    assert result.customer is not None
    assert result.vehicle is not None
    assert result.vehicle.make == "Honda"
    assert result.vehicle.model == "Civic"
    assert result.vehicle.vin == "1HGFA16588L000001"
    assert result.intake_request.status.value == "converted"


async def test_convert_attaches_to_existing_customer(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    existing = await main.create_customer_record(
        CustomerCreate(first_name="Existing", last_name="Owner"), db_session, auth
    )
    draft = await _create_draft(db_session, auth, vehicle_make="Toyota", vehicle_model="Corolla")
    result = await main.convert_intake_request_record(
        draft.id,
        IntakeRequestConvertRequest(customer_id=existing.id),
        db_session,
        auth,
    )
    # Attached to the existing customer -- no new customer row created.
    assert result.customer.id == existing.id
    assert db_session.scalar(select(func.count()).select_from(Customer)) == 1
    assert result.vehicle is not None
    assert result.vehicle.customer_id == existing.id


async def test_convert_rejects_cross_shop_customer(settings, db_session: Session) -> None:
    owner_a = await _owner_auth(settings, db_session)
    create_user(db_session, username="owner-b", password="owner-b-pass-123", settings=settings)
    _, resp_b = await login_as(
        settings, db_session, username="owner-b", password="owner-b-pass-123"
    )
    owner_b = auth_context(settings, db_session, raw_cookie_from_response(resp_b))
    customer_b = await main.create_customer_record(
        CustomerCreate(first_name="Other", last_name="Shop"), db_session, owner_b
    )
    draft_a = await _create_draft(db_session, owner_a, vehicle_make="Ford", vehicle_model="F150")

    with pytest.raises(HTTPException) as excinfo:
        await main.convert_intake_request_record(
            draft_a.id,
            IntakeRequestConvertRequest(customer_id=customer_b.id),
            db_session,
            owner_a,
        )
    assert excinfo.value.status_code == 422
    # No conversion happened; draft is untouched and no orphan rows exist.
    reread = await main.get_intake_request_record(draft_a.id, db_session, owner_a)
    assert reread.status.value != "converted"


async def test_convert_rejects_archived_customer(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer = await main.create_customer_record(
        CustomerCreate(first_name="Gone", last_name="Away"), db_session, auth
    )
    await main.archive_customer_record(customer.id, db_session, auth)
    draft = await _create_draft(db_session, auth, vehicle_make="Kia", vehicle_model="Rio")
    with pytest.raises(HTTPException) as excinfo:
        await main.convert_intake_request_record(
            draft.id,
            IntakeRequestConvertRequest(customer_id=customer.id),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409


async def test_convert_rejects_duplicate_vin_without_orphaning_customer(
    settings, db_session: Session
) -> None:
    auth = await _owner_auth(settings, db_session)
    # An active vehicle with this VIN already exists in the shop.
    existing_customer = await main.create_customer_record(
        CustomerCreate(first_name="First", last_name="Owner"), db_session, auth
    )
    await main.create_vehicle_record(
        existing_customer.id,
        VehicleCreate(make="Honda", model="Civic", vin="1HGFA16588L000009"),
        db_session,
        auth,
    )
    customers_before = db_session.scalar(select(func.count()).select_from(Customer))

    draft = await _create_draft(
        db_session,
        auth,
        vehicle_make="Honda",
        vehicle_model="Civic",
        vehicle_vin="1HGFA16588L000009",
    )
    with pytest.raises(HTTPException) as excinfo:
        await main.convert_intake_request_record(
            draft.id, IntakeRequestConvertRequest(), db_session, auth
        )
    assert excinfo.value.status_code == 409
    # Critically: the failed conversion did NOT leave an orphan customer.
    assert db_session.scalar(select(func.count()).select_from(Customer)) == customers_before
    reread = await main.get_intake_request_record(draft.id, db_session, auth)
    assert reread.status.value != "converted"


async def test_double_conversion_is_rejected(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    draft = await _create_draft(db_session, auth, vehicle_make="Mazda", vehicle_model="3")
    await main.convert_intake_request_record(
        draft.id, IntakeRequestConvertRequest(), db_session, auth
    )
    with pytest.raises(HTTPException) as excinfo:
        await main.convert_intake_request_record(
            draft.id, IntakeRequestConvertRequest(), db_session, auth
        )
    assert excinfo.value.status_code == 409


async def test_convert_payload_overrides_draft_vehicle(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    draft = await _create_draft(db_session, auth, vehicle_make="Honda", vehicle_model="Civic")
    result = await main.convert_intake_request_record(
        draft.id,
        IntakeRequestConvertRequest(vehicle_make="Acura", vehicle_model="Integra"),
        db_session,
        auth,
    )
    assert result.vehicle is not None
    assert result.vehicle.make == "Acura"
    assert result.vehicle.model == "Integra"


async def test_customer_only_conversion_when_no_vehicle(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    draft = await _create_draft(db_session, auth)
    result = await main.convert_intake_request_record(
        draft.id, IntakeRequestConvertRequest(), db_session, auth
    )
    assert result.customer is not None
    assert result.vehicle is None
    assert db_session.scalar(select(func.count()).select_from(Vehicle)) == 0


async def test_draft_rejects_invalid_vin(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    with pytest.raises(ValidationError):
        # 'I' is not a valid VIN character; the draft VIN validator rejects it
        # so a draft never stores a VIN that conversion would then reject.
        await _create_draft(db_session, auth, vehicle_vin="1HGFA16588LI00000")


async def test_update_draft_vehicle_fields_round_trip(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    draft = await _create_draft(db_session, auth)
    updated = await main.update_intake_request_record(
        draft.id,
        IntakeRequestUpdate(
            vehicle_vin="1HGFA16588L000022",
            vehicle_make="Subaru",
            vehicle_model="Outback",
        ),
        db_session,
        auth,
    )
    assert updated.vehicle_vin == "1HGFA16588L000022"
    assert updated.vehicle_make == "Subaru"
    assert updated.vehicle_model == "Outback"
