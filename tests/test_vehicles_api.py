from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict, Unpack

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.main as main
from app.auth import bootstrap_owner_account
from app.config import Settings
from app.db import Base, build_engine, build_session_factory
from app.db_models import AuthSession, Vehicle
from app.models import VehicleCreate, VehicleUpdate
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_customers_api import customer_payload


class VehiclePayload(TypedDict, total=False):
    vin: str | None
    year: int | None
    make: str
    model: str
    trim: str | None
    engine: str | None
    drivetrain: str | None
    transmission: str | None
    license_plate: str | None
    license_plate_state: str | None
    color: str | None
    current_mileage: int | None
    fleet_unit_number: str | None
    internal_notes: str | None


def vehicle_payload(**overrides: Unpack[VehiclePayload]) -> VehicleCreate:
    base: VehiclePayload = {
        "vin": "1HGCM82633A004352",
        "year": 2018,
        "make": "Honda",
        "model": "Civic",
        "trim": "EX",
        "engine": "2.0L I4",
        "drivetrain": "FWD",
        "transmission": "CVT",
        "license_plate": "8abc123",
        "license_plate_state": "ca",
        "color": "Blue",
        "current_mileage": 125000,
        "fleet_unit_number": "Unit 7",
        "internal_notes": "Owner supplied vehicle.",
    }
    base.update(overrides)
    return VehicleCreate(**base)


async def create_customer_for_auth(settings: Settings, db_session: Session, auth) -> int:  # type: ignore[no-untyped-def]
    created = await main.create_customer_record(customer_payload(), db_session, auth)
    return created.id


@pytest.mark.anyio
async def test_vehicles_require_authenticated_session(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/vehicles"), db_session, settings)
    assert excinfo.value.status_code == 401


@pytest.mark.anyio
async def test_create_vehicle_under_customer(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)

    created = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)
    assert created.customer_id == customer_id
    assert created.vin == "1HGCM82633A004352"
    assert created.license_plate == "8ABC123"
    assert created.license_plate_state == "CA"


@pytest.mark.anyio
async def test_vehicle_customer_not_found(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    with pytest.raises(HTTPException) as excinfo:
        await main.create_vehicle_record(99999, vehicle_payload(), db_session, auth)
    assert excinfo.value.status_code == 404


@pytest.mark.anyio
async def test_vehicle_cross_user_customer_rejection(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(db_session, username="other-owner", password="other-password-123")
    _, other_response = await login_as(
        settings,
        db_session,
        username="other-owner",
        password="other-password-123",
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    customer_id = await create_customer_for_auth(settings, db_session, owner_auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, other_auth)
    assert excinfo.value.status_code == 404


@pytest.mark.anyio
async def test_retrieve_and_update_vehicle(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)
    created = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)

    fetched = await main.get_vehicle_record(created.id, db_session, auth)
    assert fetched.display_name == "2018 Honda Civic EX"

    updated = await main.update_vehicle_record(
        created.id,
        VehicleUpdate(current_mileage=130000, color="Black", transmission="6MT"),
        db_session,
        auth,
    )
    assert updated.current_mileage == 130000
    assert updated.color == "Black"
    assert updated.transmission == "6MT"


@pytest.mark.anyio
async def test_list_customer_vehicles_and_global_search(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)

    first = await main.create_vehicle_record(
        customer_id,
        vehicle_payload(
            vin="1HGCM82633A004352", license_plate="8abc123", make="Honda", model="Civic"
        ),
        db_session,
        auth,
    )
    second = await main.create_vehicle_record(
        customer_id,
        vehicle_payload(
            vin=None,
            year=2020,
            make="Ford",
            model="Transit",
            license_plate="CA 55 FLEET",
            license_plate_state="CA",
        ),
        db_session,
        auth,
    )

    customer_list = await main.list_customer_vehicle_records(
        customer_id,
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search=None,
        archived=False,
    )
    assert [item.id for item in customer_list.items] == [second.id, first.id]

    search_vin = await main.list_vehicle_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search="1hgcm82633a004352",
        customer_id=None,
        archived=False,
    )
    assert [item.id for item in search_vin.items] == [first.id]

    search_plate = await main.list_vehicle_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search="55fleet",
        customer_id=None,
        archived=False,
    )
    assert [item.id for item in search_plate.items] == [second.id]


@pytest.mark.anyio
async def test_vehicle_vin_normalization_and_invalid_vin(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)

    created = await main.create_vehicle_record(
        customer_id,
        vehicle_payload(vin=" 1hgcm82633a004352 "),
        db_session,
        auth,
    )
    assert created.vin == "1HGCM82633A004352"

    with pytest.raises(HTTPException) as excinfo:
        await main.create_vehicle_record(
            customer_id,
            vehicle_payload(vin="1IOCM82633A004352"),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422
    assert "cannot contain I, O, or Q" in str(excinfo.value.detail)


@pytest.mark.anyio
async def test_duplicate_active_vin_is_rejected(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)

    await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)
    with pytest.raises(HTTPException) as excinfo:
        await main.create_vehicle_record(
            customer_id,
            vehicle_payload(license_plate="9xyz999"),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422
    assert "active vehicle with this vin already exists" in str(excinfo.value.detail).lower()


def test_vehicle_mileage_validation() -> None:
    with pytest.raises(ValidationError):
        vehicle_payload(current_mileage=-1)


@pytest.mark.anyio
async def test_vehicle_archived_filtering(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)
    created = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)

    archived = await main.archive_vehicle_record(created.id, db_session, auth)
    assert archived.vehicle.is_archived is True

    active_list = await main.list_vehicle_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search=None,
        customer_id=None,
        archived=False,
    )
    assert active_list.items == []

    archived_list = await main.list_vehicle_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search=None,
        customer_id=None,
        archived=True,
    )
    assert [item.id for item in archived_list.items] == [created.id]


@pytest.mark.anyio
async def test_vehicle_cross_user_isolation(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(db_session, username="second-owner", password="other-password-123")
    _, other_response = await login_as(
        settings,
        db_session,
        username="second-owner",
        password="other-password-123",
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    customer_id = await create_customer_for_auth(settings, db_session, owner_auth)
    vehicle = await main.create_vehicle_record(
        customer_id, vehicle_payload(), db_session, owner_auth
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.get_vehicle_record(vehicle.id, db_session, other_auth)
    assert excinfo.value.status_code == 404


def test_vehicle_restart_persistence(tmp_path: Path) -> None:
    database_path = tmp_path / "vehicles.sqlite"
    settings = Settings(
        app_env="test",
        openai_api_key="test-key",
        database_url=f"sqlite+pysqlite:///{database_path}",
        frontend_origin="http://127.0.0.1:5173",
        labor_rate=100,
        mobile_service_fee=25,
        shop_supplies_percent=5,
        parts_tax_rate=8.5,
        optimus_owner_username="owner",
        optimus_owner_password="owner-password-123",
    )
    engine = build_engine(settings.database_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings.database_url)
    first = session_factory()
    try:
        bootstrap_owner_account(settings=settings, db=first)
        owner = first.get(main.UserAccount, 1)
        assert owner is not None
        auth_session = AuthSession(
            user_id=owner.id,
            token_hash="vehicle-persistence-test",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        first.add(auth_session)
        first.commit()
        first.refresh(auth_session)
        auth = main.AuthContext(user=owner, session=auth_session)
        customer = main.create_customer(
            db=first,
            auth=auth,
            payload=customer_payload(),
        )
        vehicle = main.create_vehicle(
            db=first,
            auth=auth,
            customer_id=customer.id,
            payload=vehicle_payload(),
        )
        vehicle_id = vehicle.id
    finally:
        first.close()

    second = session_factory()
    try:
        owner = second.get(main.UserAccount, 1)
        assert owner is not None
        vehicle_row = second.get(Vehicle, vehicle_id)
        assert vehicle_row is not None
        assert vehicle_row.make == "Honda"
    finally:
        second.close()


@pytest.mark.anyio
async def test_vehicle_storage_failures_are_sanitized(
    monkeypatch, settings, db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)

    def fail_create(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise SQLAlchemyError("insert into vehicles leaked")

    monkeypatch.setattr(main, "create_vehicle", fail_create)
    caplog.set_level(logging.WARNING)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Vehicle storage is unavailable."
    assert "insert into vehicles leaked" not in caplog.text
