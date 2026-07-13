from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

import app.main as main
from app.models import (
    AppointmentCancelRequest,
    AppointmentCreate,
    AppointmentMoveRequest,
    AppointmentStatus,
    AppointmentUpdate,
    BayCreate,
    CustomerCreate,
    ScheduleBlockCreate,
    ScheduleBlockUpdate,
    ServiceLocation,
    TechnicianCreate,
    VehicleCreate,
    WorkingHoursCreate,
)
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response

pytestmark = pytest.mark.anyio

SHOP_TZ = ZoneInfo("America/Chicago")


def _future(hours: int) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


def _shop_local_utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=SHOP_TZ).astimezone(UTC)


def _conflict_codes(exc: HTTPException) -> list[str]:
    detail = cast(dict[str, object], exc.detail)
    conflicts = cast(list[dict[str, object]], detail["conflicts"])
    return [str(conflict["code"]) for conflict in conflicts]


async def _create_customer_and_vehicle(
    db_session: Session, auth, *, first_name: str = "Jamie"
) -> tuple[int, int]:
    customer = await main.create_customer_record(
        CustomerCreate(first_name=first_name, last_name="Diaz"), db_session, auth
    )
    vehicle = await main.create_vehicle_record(
        customer.id,
        VehicleCreate(year=2020, make="Toyota", model="Camry"),
        db_session,
        auth,
    )
    return customer.id, vehicle.id


async def _create_technician(db_session: Session, auth, *, first_name: str = "Alex") -> int:
    technician = await main.create_technician_record(
        TechnicianCreate(first_name=first_name, last_name="Reyes"), db_session, auth
    )
    return technician.id


async def _create_bay(db_session: Session, auth, *, name: str = "Bay 1") -> int:
    bay = await main.create_bay_record(BayCreate(name=name), db_session, auth)
    return bay.id


async def _owner_auth(settings, db_session: Session):  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    return auth_context(settings, db_session, raw_cookie_from_response(response))


async def test_scheduling_requires_authenticated_session(settings, db_session: Session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/appointments"), db_session, settings)
    assert excinfo.value.status_code == 401


async def test_create_appointment(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    created = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Oil change",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )
    assert created.status == "tentative"
    assert created.customer_id == customer_id
    assert created.vehicle_id == vehicle_id
    assert created.technician_id == technician_id


def test_appointment_rejects_end_before_start() -> None:
    start = _future(48)
    with pytest.raises(ValidationError):
        AppointmentCreate(
            customer_id=1,
            vehicle_id=1,
            technician_id=1,
            service_type="Oil change",
            start_time=start,
            end_time=start - timedelta(hours=1),
        )


async def test_appointment_rejects_past_start_time(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = datetime.now(UTC) - timedelta(hours=2)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=customer_id,
                vehicle_id=vehicle_id,
                technician_id=technician_id,
                service_type="Oil change",
                start_time=start,
                end_time=start + timedelta(hours=1),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409


async def test_technician_overlap_rejected(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    other_customer_id, other_vehicle_id = await _create_customer_and_vehicle(
        db_session, auth, first_name="Robin"
    )
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Oil change",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=other_customer_id,
                vehicle_id=other_vehicle_id,
                technician_id=technician_id,
                service_type="Brake inspection",
                start_time=start + timedelta(minutes=30),
                end_time=start + timedelta(minutes=90),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409
    assert _conflict_codes(excinfo.value)[0] == "technician_overlap"


async def test_bay_overlap_rejected(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    other_customer_id, other_vehicle_id = await _create_customer_and_vehicle(
        db_session, auth, first_name="Robin"
    )
    technician_id = await _create_technician(db_session, auth, first_name="Alex")
    other_technician_id = await _create_technician(db_session, auth, first_name="Sam")
    bay_id = await _create_bay(db_session, auth)
    start = _future(48)

    await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            bay_id=bay_id,
            service_type="Oil change",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=other_customer_id,
                vehicle_id=other_vehicle_id,
                technician_id=other_technician_id,
                bay_id=bay_id,
                service_type="Brake inspection",
                start_time=start + timedelta(minutes=30),
                end_time=start + timedelta(minutes=90),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409
    assert _conflict_codes(excinfo.value)[0] == "bay_overlap"


async def test_travel_buffer_conflict_and_clearance(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    first = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Oil change",
            service_location=ServiceLocation.MOBILE,
            start_time=start,
            end_time=start + timedelta(hours=1),
            travel_buffer_minutes=30,
        ),
        db_session,
        auth,
    )

    # Back-to-back with no gap violates the 30-minute travel buffer.
    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=customer_id,
                vehicle_id=vehicle_id,
                technician_id=technician_id,
                service_type="Next job",
                service_location=ServiceLocation.MOBILE,
                start_time=first.end_time,
                end_time=first.end_time + timedelta(hours=1),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409
    assert _conflict_codes(excinfo.value)[0] == "technician_overlap"

    # A gap that exactly satisfies the buffer succeeds.
    cleared = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Next job",
            service_location=ServiceLocation.MOBILE,
            start_time=first.end_time + timedelta(minutes=30),
            end_time=first.end_time + timedelta(minutes=90),
        ),
        db_session,
        auth,
    )
    assert cleared.id != first.id


async def test_working_hours_enforcement(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)

    future_local = (datetime.now(UTC) + timedelta(days=20)).astimezone(SHOP_TZ)
    day_of_week = future_local.weekday()
    await main.create_working_hours_record(
        WorkingHoursCreate(
            technician_id=technician_id, day_of_week=day_of_week, start_minute=480, end_minute=1020
        ),
        db_session,
        auth,
    )

    within_hours = _shop_local_utc(future_local.year, future_local.month, future_local.day, 9)
    ok = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Oil change",
            start_time=within_hours,
            end_time=within_hours + timedelta(hours=1),
        ),
        db_session,
        auth,
    )
    assert ok.status == "tentative"

    outside_hours = _shop_local_utc(future_local.year, future_local.month, future_local.day, 6)
    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=customer_id,
                vehicle_id=vehicle_id,
                technician_id=technician_id,
                service_type="Early job",
                start_time=outside_hours,
                end_time=outside_hours + timedelta(hours=1),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409
    assert _conflict_codes(excinfo.value)[0] == "working_hours"


async def test_working_hours_are_dst_aware(settings, db_session: Session) -> None:
    """The same 9am-5pm local working-hours row must map to different UTC
    instants in winter (CST, UTC-6) vs. summer (CDT, UTC-5) -- proving the
    conversion tracks America/Chicago's actual offset rather than a fixed one."""
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)

    future_year = datetime.now(UTC).year + 2
    winter_date = datetime(future_year, 1, 14, tzinfo=SHOP_TZ)  # January (CST)
    # First day in July that falls on the same weekday as winter_date (CDT).
    summer_date = next(
        datetime(future_year, 7, day, tzinfo=SHOP_TZ)
        for day in range(1, 8)
        if datetime(future_year, 7, day, tzinfo=SHOP_TZ).weekday() == winter_date.weekday()
    )
    assert winter_date.weekday() == summer_date.weekday()

    await main.create_working_hours_record(
        WorkingHoursCreate(
            technician_id=technician_id,
            day_of_week=winter_date.weekday(),
            start_minute=0,
            end_minute=1440,
        ),
        db_session,
        auth,
    )

    winter_start = _shop_local_utc(winter_date.year, winter_date.month, winter_date.day, 9)
    summer_start = _shop_local_utc(summer_date.year, summer_date.month, summer_date.day, 9)

    winter_appointment = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Winter job",
            start_time=winter_start,
            end_time=winter_start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )
    summer_appointment = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Summer job",
            start_time=summer_start,
            end_time=summer_start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )

    assert winter_appointment.start_time.hour == 15  # 9am CST -> 15:00 UTC
    assert summer_appointment.start_time.hour == 14  # 9am CDT -> 14:00 UTC


async def test_blocked_time_enforcement(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(72)

    await main.create_schedule_block_record(
        ScheduleBlockCreate(
            technician_id=technician_id,
            start_time=start - timedelta(minutes=30),
            end_time=start + timedelta(hours=2),
            reason="Army duty",
        ),
        db_session,
        auth,
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=customer_id,
                vehicle_id=vehicle_id,
                technician_id=technician_id,
                service_type="Oil change",
                start_time=start,
                end_time=start + timedelta(hours=1),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409
    assert _conflict_codes(excinfo.value)[0] == "schedule_block"


async def test_schedule_block_rejects_both_technician_and_bay(
    settings, db_session: Session
) -> None:
    """A block naming both a technician and a bay is ambiguous (does it mean
    "this tech is out" OR "this bay is out", or the intersection of both?) --
    the model must reject it rather than silently applying the broader
    OR semantics from `_schedule_block_applies`."""
    auth = await _owner_auth(settings, db_session)
    technician_id = await _create_technician(db_session, auth)
    bay_id = await _create_bay(db_session, auth)
    start = _future(72)

    with pytest.raises(ValidationError):
        ScheduleBlockCreate(
            technician_id=technician_id,
            bay_id=bay_id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            reason="Ambiguous scope",
        )

    single_scope = await main.create_schedule_block_record(
        ScheduleBlockCreate(
            technician_id=technician_id,
            start_time=start,
            end_time=start + timedelta(hours=1),
            reason="Technician only",
        ),
        db_session,
        auth,
    )
    with pytest.raises(HTTPException) as excinfo:
        await main.update_schedule_block_record(
            single_scope.id,
            ScheduleBlockUpdate(bay_id=bay_id),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422


async def test_cannot_cancel_completed_appointment(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    created = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Oil change",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )
    completed = await main.update_appointment_record(
        created.id,
        AppointmentUpdate(status=AppointmentStatus.COMPLETED),
        db_session,
        auth,
    )
    assert completed.status == "completed"

    with pytest.raises(HTTPException) as excinfo:
        await main.cancel_appointment_record(
            created.id,
            AppointmentCancelRequest(cancellation_reason="Trying anyway"),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409


async def test_move_appointment(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    created = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Oil change",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )

    new_start = start + timedelta(days=1)
    moved = await main.move_appointment_record(
        created.id,
        AppointmentMoveRequest(start_time=new_start, end_time=new_start + timedelta(hours=1)),
        db_session,
        auth,
    )
    assert moved.start_time == new_start


async def test_move_appointment_revalidates_conflicts(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    blocker = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Existing job",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )
    movable = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Movable job",
            start_time=start + timedelta(hours=3),
            end_time=start + timedelta(hours=4),
        ),
        db_session,
        auth,
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.move_appointment_record(
            movable.id,
            AppointmentMoveRequest(start_time=blocker.start_time, end_time=blocker.end_time),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409


async def test_cancellation_releases_slot(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    created = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Oil change",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )

    canceled = await main.cancel_appointment_record(
        created.id,
        AppointmentCancelRequest(cancellation_reason="Customer rescheduled"),
        db_session,
        auth,
    )
    assert canceled.status == "canceled"
    assert canceled.cancellation_reason == "Customer rescheduled"

    # The exact same slot is now free for a new appointment.
    replacement = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Replacement job",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )
    assert replacement.id != created.id


async def test_cancel_already_canceled_appointment_conflicts(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    created = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Oil change",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )
    await main.cancel_appointment_record(
        created.id, AppointmentCancelRequest(cancellation_reason="First cancel"), db_session, auth
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.cancel_appointment_record(
            created.id,
            AppointmentCancelRequest(cancellation_reason="Second cancel"),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409


async def test_appointment_rejects_invalid_customer(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    _, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=999999,
                vehicle_id=vehicle_id,
                technician_id=technician_id,
                service_type="Oil change",
                start_time=start,
                end_time=start + timedelta(hours=1),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422


async def test_appointment_rejects_vehicle_not_owned_by_customer(
    settings, db_session: Session
) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, _ = await _create_customer_and_vehicle(db_session, auth, first_name="Jamie")
    _, other_vehicle_id = await _create_customer_and_vehicle(db_session, auth, first_name="Robin")
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=customer_id,
                vehicle_id=other_vehicle_id,
                technician_id=technician_id,
                service_type="Oil change",
                start_time=start,
                end_time=start + timedelta(hours=1),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422


async def test_appointment_rejects_invalid_technician(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    start = _future(48)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=customer_id,
                vehicle_id=vehicle_id,
                technician_id=999999,
                service_type="Oil change",
                start_time=start,
                end_time=start + timedelta(hours=1),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422


async def test_appointment_rejects_invalid_bay(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=customer_id,
                vehicle_id=vehicle_id,
                technician_id=technician_id,
                bay_id=999999,
                service_type="Oil change",
                start_time=start,
                end_time=start + timedelta(hours=1),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422


async def test_appointment_rejects_invalid_work_order(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_appointment_record(
            AppointmentCreate(
                customer_id=customer_id,
                vehicle_id=vehicle_id,
                technician_id=technician_id,
                work_order_id=999999,
                service_type="Oil change",
                start_time=start,
                end_time=start + timedelta(hours=1),
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422


async def test_appointment_cross_owner_isolation(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    owner_auth = await _owner_auth(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, owner_auth)
    technician_id = await _create_technician(db_session, owner_auth)
    start = _future(48)

    created = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Oil change",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        owner_auth,
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.get_appointment_record(created.id, db_session, other_auth)
    assert excinfo.value.status_code == 404

    listed = await main.list_appointment_records(
        db_session,
        settings,
        other_auth,
        page=1,
        page_size=20,
        date_from=None,
        date_to=None,
        technician_id=None,
        bay_id=None,
        status_filter=None,
        customer_id=None,
        vehicle_id=None,
    )
    assert listed.items == []


async def test_update_appointment_rejects_editing_canceled(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    customer_id, vehicle_id = await _create_customer_and_vehicle(db_session, auth)
    technician_id = await _create_technician(db_session, auth)
    start = _future(48)

    created = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            technician_id=technician_id,
            service_type="Oil change",
            start_time=start,
            end_time=start + timedelta(hours=1),
        ),
        db_session,
        auth,
    )
    await main.cancel_appointment_record(
        created.id,
        AppointmentCancelRequest(cancellation_reason="No longer needed"),
        db_session,
        auth,
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.update_appointment_record(
            created.id,
            AppointmentUpdate(internal_notes="Trying to edit anyway"),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422
