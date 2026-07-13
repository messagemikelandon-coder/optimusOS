from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id, ensure_utc
from app.config import Settings
from app.customer_store import display_name as customer_display_name
from app.db_models import (
    Appointment,
    Bay,
    Customer,
    ScheduleBlock,
    Technician,
    Vehicle,
    WorkingHours,
    WorkOrder,
)
from app.models import (
    AppointmentConflictDetail,
    AppointmentCreate,
    AppointmentListResponse,
    AppointmentMoveRequest,
    AppointmentRead,
    AppointmentStatus,
    AppointmentUpdate,
    AvailabilityResponse,
    AvailabilityWindow,
    BayArchiveResponse,
    BayCreate,
    BayListResponse,
    BayRead,
    BayUpdate,
    ScheduleBlockCreate,
    ScheduleBlockListResponse,
    ScheduleBlockRead,
    ScheduleBlockUpdate,
    ServiceLocation,
    WorkingHoursCreate,
    WorkingHoursListResponse,
    WorkingHoursRead,
    WorkingHoursUpdate,
)
from app.technician_store import display_name as technician_display_name
from app.vehicle_store import vehicle_display_name

# The application timezone. Working hours recur weekly by local day/time and
# therefore must not shift with DST -- appointment UTC instants are converted
# to this zone only for the purpose of comparing them against configured
# working hours, never for storage.
SHOP_TIMEZONE = ZoneInfo("America/Chicago")

_ACTIVE_STATUSES = (
    AppointmentStatus.TENTATIVE,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.IN_PROGRESS,
)

# Travel buffer is capped (see AppointmentBase.travel_buffer_minutes) so a
# fixed pad safely captures every appointment whose buffered window could
# possibly reach into the requested slot, without scanning the whole table.
_CONFLICT_QUERY_PAD = timedelta(hours=8)


class SchedulingStoreError(ValueError):
    pass


class SchedulingNotFoundError(SchedulingStoreError):
    pass


@dataclass(slots=True)
class SchedulingConflictError(SchedulingStoreError):
    message: str
    conflicts: list[AppointmentConflictDetail] = field(default_factory=list)

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)

    def as_detail(self) -> dict[str, object]:
        return {
            "message": self.message,
            "conflicts": [conflict.model_dump(mode="json") for conflict in self.conflicts],
        }


# ---- Shared validation helpers ----


def _validate_customer(db: Session, auth: AuthContext, customer_id: int) -> Customer:
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id, Customer.owner_user_id == effective_owner_id(auth)
        )
    )
    if customer is None:
        raise SchedulingStoreError("Selected customer was not found.")
    return customer


def _validate_vehicle(db: Session, auth: AuthContext, vehicle_id: int, customer_id: int) -> Vehicle:
    vehicle = db.scalar(
        select(Vehicle).where(
            Vehicle.id == vehicle_id, Vehicle.owner_user_id == effective_owner_id(auth)
        )
    )
    if vehicle is None:
        raise SchedulingStoreError("Selected vehicle was not found.")
    if vehicle.customer_id != customer_id:
        raise SchedulingStoreError("Selected vehicle does not belong to the selected customer.")
    return vehicle


def _validate_technician(db: Session, auth: AuthContext, technician_id: int) -> Technician:
    technician = db.scalar(
        select(Technician).where(
            Technician.id == technician_id, Technician.owner_user_id == effective_owner_id(auth)
        )
    )
    if technician is None:
        raise SchedulingStoreError("Selected technician was not found.")
    return technician


def _validate_bay(db: Session, auth: AuthContext, bay_id: int | None) -> Bay | None:
    if bay_id is None:
        return None
    bay = db.scalar(
        select(Bay).where(Bay.id == bay_id, Bay.owner_user_id == effective_owner_id(auth))
    )
    if bay is None:
        raise SchedulingStoreError("Selected bay was not found.")
    return bay


def _validate_work_order(db: Session, auth: AuthContext, work_order_id: int | None) -> None:
    if work_order_id is None:
        return
    work_order = db.scalar(
        select(WorkOrder).where(
            WorkOrder.id == work_order_id,
            WorkOrder.owner_user_id == effective_owner_id(auth),
        )
    )
    if work_order is None:
        raise SchedulingStoreError("Selected work order was not found.")


# ---- Bays ----


def _bay_owner_query(auth: AuthContext) -> Select[tuple[Bay]]:
    return select(Bay).where(Bay.owner_user_id == effective_owner_id(auth))


def _get_bay(db: Session, auth: AuthContext, bay_id: int) -> Bay:
    bay = db.scalar(_bay_owner_query(auth).where(Bay.id == bay_id))
    if bay is None:
        raise SchedulingNotFoundError("Bay not found.")
    return bay


def _bay_to_read(bay: Bay) -> BayRead:
    return BayRead(
        id=bay.id,
        name=bay.name,
        notes=bay.notes,
        is_archived=bay.is_archived,
        created_at=ensure_utc(bay.created_at),
        updated_at=ensure_utc(bay.updated_at),
    )


def create_bay(*, db: Session, auth: AuthContext, payload: BayCreate) -> BayRead:
    bay = Bay(owner_user_id=effective_owner_id(auth), name=payload.name, notes=payload.notes)
    db.add(bay)
    db.commit()
    db.refresh(bay)
    return _bay_to_read(bay)


def get_bay(*, db: Session, auth: AuthContext, bay_id: int) -> BayRead:
    return _bay_to_read(_get_bay(db, auth, bay_id))


def update_bay(*, db: Session, auth: AuthContext, bay_id: int, payload: BayUpdate) -> BayRead:
    bay = _get_bay(db, auth, bay_id)
    fields_set = payload.model_fields_set
    if "name" in fields_set and payload.name is not None:
        bay.name = payload.name
    if "notes" in fields_set:
        bay.notes = payload.notes
    db.add(bay)
    db.commit()
    db.refresh(bay)
    return _bay_to_read(bay)


def archive_bay(*, db: Session, auth: AuthContext, bay_id: int) -> BayArchiveResponse:
    bay = _get_bay(db, auth, bay_id)
    bay.is_archived = True
    db.add(bay)
    db.commit()
    db.refresh(bay)
    return BayArchiveResponse(bay=_bay_to_read(bay))


def list_bays(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    archived: bool,
) -> BayListResponse:
    if page_size > settings.customers_max_page_size:
        raise SchedulingStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise SchedulingStoreError("Page must be 1 or greater.")

    query = _bay_owner_query(auth).where(Bay.is_archived == archived)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    bays = db.scalars(
        query.order_by(Bay.name.asc(), Bay.id.asc()).offset(offset).limit(page_size)
    ).all()
    return BayListResponse(
        items=[_bay_to_read(bay) for bay in bays],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(bays) < total,
    )


# ---- Working hours ----


def _get_working_hours(db: Session, auth: AuthContext, working_hours_id: int) -> WorkingHours:
    row = db.scalar(
        select(WorkingHours).where(
            WorkingHours.id == working_hours_id,
            WorkingHours.owner_user_id == effective_owner_id(auth),
        )
    )
    if row is None:
        raise SchedulingNotFoundError("Working hours entry not found.")
    return row


def _working_hours_to_read(row: WorkingHours) -> WorkingHoursRead:
    return WorkingHoursRead(
        id=row.id,
        technician_id=row.technician_id,
        day_of_week=row.day_of_week,
        start_minute=row.start_minute,
        end_minute=row.end_minute,
        created_at=ensure_utc(row.created_at),
        updated_at=ensure_utc(row.updated_at),
    )


def create_working_hours(
    *, db: Session, auth: AuthContext, payload: WorkingHoursCreate
) -> WorkingHoursRead:
    _validate_technician(db, auth, payload.technician_id)
    row = WorkingHours(
        owner_user_id=effective_owner_id(auth),
        technician_id=payload.technician_id,
        day_of_week=payload.day_of_week,
        start_minute=payload.start_minute,
        end_minute=payload.end_minute,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _working_hours_to_read(row)


def update_working_hours(
    *, db: Session, auth: AuthContext, working_hours_id: int, payload: WorkingHoursUpdate
) -> WorkingHoursRead:
    row = _get_working_hours(db, auth, working_hours_id)
    fields_set = payload.model_fields_set
    start_minute = (
        payload.start_minute
        if "start_minute" in fields_set and payload.start_minute is not None
        else row.start_minute
    )
    end_minute = (
        payload.end_minute
        if "end_minute" in fields_set and payload.end_minute is not None
        else row.end_minute
    )
    if end_minute <= start_minute:
        raise SchedulingStoreError("end_minute must be later than start_minute.")
    if "day_of_week" in fields_set and payload.day_of_week is not None:
        row.day_of_week = payload.day_of_week
    row.start_minute = start_minute
    row.end_minute = end_minute
    db.add(row)
    db.commit()
    db.refresh(row)
    return _working_hours_to_read(row)


def delete_working_hours(*, db: Session, auth: AuthContext, working_hours_id: int) -> None:
    row = _get_working_hours(db, auth, working_hours_id)
    db.delete(row)
    db.commit()


def list_working_hours(
    *, db: Session, auth: AuthContext, technician_id: int
) -> WorkingHoursListResponse:
    _validate_technician(db, auth, technician_id)
    rows = db.scalars(
        select(WorkingHours)
        .where(
            WorkingHours.owner_user_id == effective_owner_id(auth),
            WorkingHours.technician_id == technician_id,
        )
        .order_by(WorkingHours.day_of_week.asc(), WorkingHours.start_minute.asc())
    ).all()
    return WorkingHoursListResponse(items=[_working_hours_to_read(row) for row in rows])


# ---- Schedule blocks ----


def _get_schedule_block(db: Session, auth: AuthContext, block_id: int) -> ScheduleBlock:
    block = db.scalar(
        select(ScheduleBlock).where(
            ScheduleBlock.id == block_id,
            ScheduleBlock.owner_user_id == effective_owner_id(auth),
        )
    )
    if block is None:
        raise SchedulingNotFoundError("Schedule block not found.")
    return block


def _schedule_block_to_read(
    db: Session, auth: AuthContext, block: ScheduleBlock
) -> ScheduleBlockRead:
    technician = (
        db.scalar(
            select(Technician).where(
                Technician.id == block.technician_id,
                Technician.owner_user_id == effective_owner_id(auth),
            )
        )
        if block.technician_id is not None
        else None
    )
    bay = (
        db.scalar(
            select(Bay).where(Bay.id == block.bay_id, Bay.owner_user_id == effective_owner_id(auth))
        )
        if block.bay_id is not None
        else None
    )
    return ScheduleBlockRead(
        id=block.id,
        technician_id=block.technician_id,
        bay_id=block.bay_id,
        start_time=ensure_utc(block.start_time),
        end_time=ensure_utc(block.end_time),
        reason=block.reason,
        notes=block.notes,
        technician_display_name=technician_display_name(technician) if technician else None,
        bay_name=bay.name if bay else None,
        created_at=ensure_utc(block.created_at),
        updated_at=ensure_utc(block.updated_at),
    )


def create_schedule_block(
    *, db: Session, auth: AuthContext, payload: ScheduleBlockCreate
) -> ScheduleBlockRead:
    if payload.technician_id is not None:
        _validate_technician(db, auth, payload.technician_id)
    if payload.bay_id is not None:
        _validate_bay(db, auth, payload.bay_id)
    block = ScheduleBlock(
        owner_user_id=effective_owner_id(auth),
        technician_id=payload.technician_id,
        bay_id=payload.bay_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        reason=payload.reason,
        notes=payload.notes,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return _schedule_block_to_read(db, auth, block)


def get_schedule_block(*, db: Session, auth: AuthContext, block_id: int) -> ScheduleBlockRead:
    return _schedule_block_to_read(db, auth, _get_schedule_block(db, auth, block_id))


def update_schedule_block(
    *, db: Session, auth: AuthContext, block_id: int, payload: ScheduleBlockUpdate
) -> ScheduleBlockRead:
    block = _get_schedule_block(db, auth, block_id)
    fields_set = payload.model_fields_set
    if "technician_id" in fields_set:
        if payload.technician_id is not None:
            _validate_technician(db, auth, payload.technician_id)
        block.technician_id = payload.technician_id
    if "bay_id" in fields_set:
        if payload.bay_id is not None:
            _validate_bay(db, auth, payload.bay_id)
        block.bay_id = payload.bay_id
    if block.technician_id is not None and block.bay_id is not None:
        raise SchedulingStoreError(
            "A schedule block can target a technician or a bay, not both -- create two"
            " separate blocks if both need to be unavailable."
        )
    start_time = (
        payload.start_time
        if "start_time" in fields_set and payload.start_time is not None
        else block.start_time
    )
    end_time = (
        payload.end_time
        if "end_time" in fields_set and payload.end_time is not None
        else block.end_time
    )
    if ensure_utc(end_time) <= ensure_utc(start_time):
        raise SchedulingStoreError("end_time must be later than start_time.")
    block.start_time = start_time
    block.end_time = end_time
    if "reason" in fields_set and payload.reason is not None:
        block.reason = payload.reason
    if "notes" in fields_set:
        block.notes = payload.notes
    db.add(block)
    db.commit()
    db.refresh(block)
    return _schedule_block_to_read(db, auth, block)


def delete_schedule_block(*, db: Session, auth: AuthContext, block_id: int) -> None:
    block = _get_schedule_block(db, auth, block_id)
    db.delete(block)
    db.commit()


def list_schedule_blocks(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    technician_id: int | None = None,
    bay_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> ScheduleBlockListResponse:
    if page_size > settings.customers_max_page_size:
        raise SchedulingStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise SchedulingStoreError("Page must be 1 or greater.")

    query = select(ScheduleBlock).where(ScheduleBlock.owner_user_id == effective_owner_id(auth))
    if technician_id is not None:
        query = query.where(ScheduleBlock.technician_id == technician_id)
    if bay_id is not None:
        query = query.where(ScheduleBlock.bay_id == bay_id)
    if date_from is not None:
        query = query.where(ScheduleBlock.end_time > date_from)
    if date_to is not None:
        query = query.where(ScheduleBlock.start_time < date_to)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    blocks = db.scalars(
        query.order_by(ScheduleBlock.start_time.asc()).offset(offset).limit(page_size)
    ).all()
    return ScheduleBlockListResponse(
        items=[_schedule_block_to_read(db, auth, block) for block in blocks],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(blocks) < total,
    )


# ---- Availability / conflict engine ----


def _schedule_block_applies(
    block: ScheduleBlock, *, technician_id: int, bay_id: int | None
) -> bool:
    if block.technician_id is not None and block.technician_id == technician_id:
        return True
    if block.bay_id is not None and bay_id is not None and block.bay_id == bay_id:
        return True
    return block.technician_id is None and block.bay_id is None


def _technician_conflicts(
    db: Session,
    auth: AuthContext,
    *,
    technician_id: int,
    start_time: datetime,
    end_time: datetime,
    travel_buffer_minutes: int,
    exclude_appointment_id: int | None,
) -> list[Appointment]:
    query = select(Appointment).where(
        Appointment.owner_user_id == effective_owner_id(auth),
        Appointment.technician_id == technician_id,
        Appointment.status.in_([status.value for status in _ACTIVE_STATUSES]),
        Appointment.start_time < end_time + _CONFLICT_QUERY_PAD,
        Appointment.end_time > start_time - _CONFLICT_QUERY_PAD,
    )
    if exclude_appointment_id is not None:
        query = query.where(Appointment.id != exclude_appointment_id)
    candidates = db.scalars(query).all()
    conflicts = []
    for candidate in candidates:
        buffer = timedelta(minutes=max(travel_buffer_minutes, candidate.travel_buffer_minutes))
        candidate_start = ensure_utc(candidate.start_time)
        candidate_end = ensure_utc(candidate.end_time)
        if not (candidate_end + buffer <= start_time or end_time + buffer <= candidate_start):
            conflicts.append(candidate)
    return conflicts


def _bay_conflicts(
    db: Session,
    auth: AuthContext,
    *,
    bay_id: int | None,
    start_time: datetime,
    end_time: datetime,
    exclude_appointment_id: int | None,
) -> list[Appointment]:
    if bay_id is None:
        return []
    query = select(Appointment).where(
        Appointment.owner_user_id == effective_owner_id(auth),
        Appointment.bay_id == bay_id,
        Appointment.status.in_([status.value for status in _ACTIVE_STATUSES]),
        Appointment.start_time < end_time,
        Appointment.end_time > start_time,
    )
    if exclude_appointment_id is not None:
        query = query.where(Appointment.id != exclude_appointment_id)
    return list(db.scalars(query).all())


def _schedule_block_conflicts(
    db: Session,
    auth: AuthContext,
    *,
    technician_id: int,
    bay_id: int | None,
    start_time: datetime,
    end_time: datetime,
) -> list[ScheduleBlock]:
    query = select(ScheduleBlock).where(
        ScheduleBlock.owner_user_id == effective_owner_id(auth),
        ScheduleBlock.start_time < end_time,
        ScheduleBlock.end_time > start_time,
    )
    candidates = db.scalars(query).all()
    return [
        block
        for block in candidates
        if _schedule_block_applies(block, technician_id=technician_id, bay_id=bay_id)
    ]


def _working_hours_conflict(
    db: Session,
    auth: AuthContext,
    *,
    technician_id: int,
    start_time: datetime,
    end_time: datetime,
) -> AppointmentConflictDetail | None:
    has_any_hours = db.scalar(
        select(func.count())
        .select_from(WorkingHours)
        .where(
            WorkingHours.owner_user_id == effective_owner_id(auth),
            WorkingHours.technician_id == technician_id,
        )
    )
    if not has_any_hours:
        # No working hours configured for this technician yet -- treat as
        # unrestricted rather than blocking every appointment by default.
        return None

    start_local = ensure_utc(start_time).astimezone(SHOP_TIMEZONE)
    end_local = ensure_utc(end_time).astimezone(SHOP_TIMEZONE)
    if start_local.date() != end_local.date():
        return AppointmentConflictDetail(
            code="working_hours",
            message="Appointments must start and end on the same local day to be validated"
            " against working hours.",
        )

    start_minute = start_local.hour * 60 + start_local.minute
    end_minute = end_local.hour * 60 + end_local.minute
    day_of_week = start_local.weekday()
    windows = db.scalars(
        select(WorkingHours).where(
            WorkingHours.owner_user_id == effective_owner_id(auth),
            WorkingHours.technician_id == technician_id,
            WorkingHours.day_of_week == day_of_week,
        )
    ).all()
    for window in windows:
        if window.start_minute <= start_minute and end_minute <= window.end_minute:
            return None
    return AppointmentConflictDetail(
        code="working_hours",
        message="The selected time is outside the technician's working hours.",
    )


def _lock_scheduling_rows(db: Session, *, technician_id: int, bay_id: int | None) -> None:
    # Serializes concurrent conflict-check-then-insert requests for the same
    # technician/bay -- mirrors app/payment_store.py's row-lock pattern.
    # SQLite (used by the test suite) ignores FOR UPDATE; Postgres enforces it.
    db.execute(select(Technician.id).where(Technician.id == technician_id).with_for_update())
    if bay_id is not None:
        db.execute(select(Bay.id).where(Bay.id == bay_id).with_for_update())


def _validate_slot(
    db: Session,
    auth: AuthContext,
    *,
    technician_id: int,
    bay_id: int | None,
    start_time: datetime,
    end_time: datetime,
    travel_buffer_minutes: int,
    exclude_appointment_id: int | None = None,
) -> None:
    start_time = ensure_utc(start_time)
    end_time = ensure_utc(end_time)
    if end_time <= start_time:
        raise SchedulingStoreError("end_time must be later than start_time.")

    conflicts: list[AppointmentConflictDetail] = []

    if start_time < datetime.now(UTC):
        conflicts.append(
            AppointmentConflictDetail(
                code="past_time", message="Appointments cannot be scheduled in the past."
            )
        )

    working_hours_conflict = _working_hours_conflict(
        db, auth, technician_id=technician_id, start_time=start_time, end_time=end_time
    )
    if working_hours_conflict is not None:
        conflicts.append(working_hours_conflict)

    for candidate in _technician_conflicts(
        db,
        auth,
        technician_id=technician_id,
        start_time=start_time,
        end_time=end_time,
        travel_buffer_minutes=travel_buffer_minutes,
        exclude_appointment_id=exclude_appointment_id,
    ):
        conflicts.append(
            AppointmentConflictDetail(
                code="technician_overlap",
                message="The technician is already booked (including travel buffer) during"
                " this time.",
                conflicting_appointment_id=candidate.id,
            )
        )

    for candidate in _bay_conflicts(
        db,
        auth,
        bay_id=bay_id,
        start_time=start_time,
        end_time=end_time,
        exclude_appointment_id=exclude_appointment_id,
    ):
        conflicts.append(
            AppointmentConflictDetail(
                code="bay_overlap",
                message="The bay is already booked during this time.",
                conflicting_appointment_id=candidate.id,
            )
        )

    for block in _schedule_block_conflicts(
        db,
        auth,
        technician_id=technician_id,
        bay_id=bay_id,
        start_time=start_time,
        end_time=end_time,
    ):
        conflicts.append(
            AppointmentConflictDetail(
                code="schedule_block",
                message=f"Unavailable: {block.reason}",
                conflicting_schedule_block_id=block.id,
            )
        )

    if conflicts:
        raise SchedulingConflictError("This time slot is unavailable.", conflicts=conflicts)


# ---- Appointments ----


def _appointment_owner_query(auth: AuthContext) -> Select[tuple[Appointment]]:
    return select(Appointment).where(Appointment.owner_user_id == effective_owner_id(auth))


def _get_appointment(db: Session, auth: AuthContext, appointment_id: int) -> Appointment:
    appointment = db.scalar(_appointment_owner_query(auth).where(Appointment.id == appointment_id))
    if appointment is None:
        raise SchedulingNotFoundError("Appointment not found.")
    return appointment


def _appointment_to_read(
    db: Session, auth: AuthContext, appointment: Appointment
) -> AppointmentRead:
    customer = db.get(Customer, appointment.customer_id)
    vehicle = db.get(Vehicle, appointment.vehicle_id)
    technician = db.get(Technician, appointment.technician_id)
    bay = db.get(Bay, appointment.bay_id) if appointment.bay_id is not None else None
    return AppointmentRead(
        id=appointment.id,
        customer_id=appointment.customer_id,
        vehicle_id=appointment.vehicle_id,
        work_order_id=appointment.work_order_id,
        technician_id=appointment.technician_id,
        bay_id=appointment.bay_id,
        service_type=appointment.service_type,
        service_location=ServiceLocation(appointment.service_location),
        start_time=ensure_utc(appointment.start_time),
        end_time=ensure_utc(appointment.end_time),
        travel_buffer_minutes=appointment.travel_buffer_minutes,
        status=AppointmentStatus(appointment.status),
        customer_notes=appointment.customer_notes,
        internal_notes=appointment.internal_notes,
        customer_display_name=customer_display_name(customer) if customer else None,
        vehicle_display_name=vehicle_display_name(vehicle) if vehicle else None,
        technician_display_name=technician_display_name(technician) if technician else None,
        bay_name=bay.name if bay else None,
        created_at=ensure_utc(appointment.created_at),
        updated_at=ensure_utc(appointment.updated_at),
        canceled_at=ensure_utc(appointment.canceled_at) if appointment.canceled_at else None,
        cancellation_reason=appointment.cancellation_reason,
    )


def create_appointment(
    *, db: Session, auth: AuthContext, payload: AppointmentCreate
) -> AppointmentRead:
    _validate_customer(db, auth, payload.customer_id)
    _validate_vehicle(db, auth, payload.vehicle_id, payload.customer_id)
    _validate_technician(db, auth, payload.technician_id)
    _validate_bay(db, auth, payload.bay_id)
    _validate_work_order(db, auth, payload.work_order_id)

    _lock_scheduling_rows(db, technician_id=payload.technician_id, bay_id=payload.bay_id)
    _validate_slot(
        db,
        auth,
        technician_id=payload.technician_id,
        bay_id=payload.bay_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        travel_buffer_minutes=payload.travel_buffer_minutes,
    )

    appointment = Appointment(
        owner_user_id=effective_owner_id(auth),
        customer_id=payload.customer_id,
        vehicle_id=payload.vehicle_id,
        work_order_id=payload.work_order_id,
        technician_id=payload.technician_id,
        bay_id=payload.bay_id,
        service_type=payload.service_type,
        service_location=payload.service_location,
        start_time=payload.start_time,
        end_time=payload.end_time,
        travel_buffer_minutes=payload.travel_buffer_minutes,
        status=payload.status.value,
        customer_notes=payload.customer_notes,
        internal_notes=payload.internal_notes,
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return _appointment_to_read(db, auth, appointment)


def get_appointment(*, db: Session, auth: AuthContext, appointment_id: int) -> AppointmentRead:
    return _appointment_to_read(db, auth, _get_appointment(db, auth, appointment_id))


def update_appointment(
    *, db: Session, auth: AuthContext, appointment_id: int, payload: AppointmentUpdate
) -> AppointmentRead:
    appointment = _get_appointment(db, auth, appointment_id)
    fields_set = payload.model_fields_set

    if appointment.status == AppointmentStatus.CANCELED.value:
        raise SchedulingStoreError("A canceled appointment cannot be edited.")

    customer_id = (
        payload.customer_id
        if "customer_id" in fields_set and payload.customer_id is not None
        else appointment.customer_id
    )
    vehicle_id = (
        payload.vehicle_id
        if "vehicle_id" in fields_set and payload.vehicle_id is not None
        else appointment.vehicle_id
    )
    technician_id = (
        payload.technician_id
        if "technician_id" in fields_set and payload.technician_id is not None
        else appointment.technician_id
    )
    bay_id = payload.bay_id if "bay_id" in fields_set else appointment.bay_id
    start_time = (
        payload.start_time
        if "start_time" in fields_set and payload.start_time is not None
        else ensure_utc(appointment.start_time)
    )
    end_time = (
        payload.end_time
        if "end_time" in fields_set and payload.end_time is not None
        else ensure_utc(appointment.end_time)
    )
    travel_buffer_minutes = (
        payload.travel_buffer_minutes
        if "travel_buffer_minutes" in fields_set and payload.travel_buffer_minutes is not None
        else appointment.travel_buffer_minutes
    )

    if customer_id != appointment.customer_id:
        _validate_customer(db, auth, customer_id)
    if vehicle_id != appointment.vehicle_id or customer_id != appointment.customer_id:
        _validate_vehicle(db, auth, vehicle_id, customer_id)
    if technician_id != appointment.technician_id:
        _validate_technician(db, auth, technician_id)
    if bay_id != appointment.bay_id:
        _validate_bay(db, auth, bay_id)
    if "work_order_id" in fields_set:
        _validate_work_order(db, auth, payload.work_order_id)

    slot_changed = (
        technician_id != appointment.technician_id
        or bay_id != appointment.bay_id
        or start_time != ensure_utc(appointment.start_time)
        or end_time != ensure_utc(appointment.end_time)
        or travel_buffer_minutes != appointment.travel_buffer_minutes
    )
    if slot_changed:
        _lock_scheduling_rows(db, technician_id=technician_id, bay_id=bay_id)
        _validate_slot(
            db,
            auth,
            technician_id=technician_id,
            bay_id=bay_id,
            start_time=start_time,
            end_time=end_time,
            travel_buffer_minutes=travel_buffer_minutes,
            exclude_appointment_id=appointment.id,
        )

    appointment.customer_id = customer_id
    appointment.vehicle_id = vehicle_id
    appointment.technician_id = technician_id
    appointment.bay_id = bay_id
    appointment.start_time = start_time
    appointment.end_time = end_time
    appointment.travel_buffer_minutes = travel_buffer_minutes
    if "work_order_id" in fields_set:
        appointment.work_order_id = payload.work_order_id
    if "service_type" in fields_set and payload.service_type is not None:
        appointment.service_type = payload.service_type
    if "service_location" in fields_set and payload.service_location is not None:
        appointment.service_location = payload.service_location
    if "status" in fields_set and payload.status is not None:
        appointment.status = payload.status.value
    if "customer_notes" in fields_set:
        appointment.customer_notes = payload.customer_notes
    if "internal_notes" in fields_set:
        appointment.internal_notes = payload.internal_notes

    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return _appointment_to_read(db, auth, appointment)


def move_appointment(
    *, db: Session, auth: AuthContext, appointment_id: int, payload: AppointmentMoveRequest
) -> AppointmentRead:
    appointment = _get_appointment(db, auth, appointment_id)
    if appointment.status == AppointmentStatus.CANCELED.value:
        raise SchedulingStoreError("A canceled appointment cannot be moved.")

    technician_id = (
        payload.technician_id if payload.technician_id is not None else appointment.technician_id
    )
    bay_id = payload.bay_id if payload.bay_id is not None else appointment.bay_id
    travel_buffer_minutes = (
        payload.travel_buffer_minutes
        if payload.travel_buffer_minutes is not None
        else appointment.travel_buffer_minutes
    )

    if technician_id != appointment.technician_id:
        _validate_technician(db, auth, technician_id)
    if bay_id != appointment.bay_id:
        _validate_bay(db, auth, bay_id)

    _lock_scheduling_rows(db, technician_id=technician_id, bay_id=bay_id)
    _validate_slot(
        db,
        auth,
        technician_id=technician_id,
        bay_id=bay_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        travel_buffer_minutes=travel_buffer_minutes,
        exclude_appointment_id=appointment.id,
    )

    appointment.technician_id = technician_id
    appointment.bay_id = bay_id
    appointment.start_time = payload.start_time
    appointment.end_time = payload.end_time
    appointment.travel_buffer_minutes = travel_buffer_minutes
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return _appointment_to_read(db, auth, appointment)


def cancel_appointment(
    *, db: Session, auth: AuthContext, appointment_id: int, cancellation_reason: str
) -> AppointmentRead:
    appointment = _get_appointment(db, auth, appointment_id)
    if appointment.status == AppointmentStatus.CANCELED.value:
        raise SchedulingConflictError(
            "This appointment is already canceled.",
            conflicts=[
                AppointmentConflictDetail(
                    code="already_canceled", message="This appointment is already canceled."
                )
            ],
        )
    if appointment.status == AppointmentStatus.COMPLETED.value:
        raise SchedulingConflictError(
            "A completed appointment cannot be canceled.",
            conflicts=[
                AppointmentConflictDetail(
                    code="already_completed", message="A completed appointment cannot be canceled."
                )
            ],
        )
    appointment.status = AppointmentStatus.CANCELED.value
    appointment.canceled_at = datetime.now(UTC)
    appointment.cancellation_reason = cancellation_reason
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return _appointment_to_read(db, auth, appointment)


def list_appointments(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    technician_id: int | None = None,
    bay_id: int | None = None,
    status_filter: AppointmentStatus | None = None,
    customer_id: int | None = None,
    vehicle_id: int | None = None,
) -> AppointmentListResponse:
    if page_size > settings.customers_max_page_size:
        raise SchedulingStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise SchedulingStoreError("Page must be 1 or greater.")

    query = _appointment_owner_query(auth)
    if date_from is not None:
        query = query.where(Appointment.end_time > date_from)
    if date_to is not None:
        query = query.where(Appointment.start_time < date_to)
    if technician_id is not None:
        query = query.where(Appointment.technician_id == technician_id)
    if bay_id is not None:
        query = query.where(Appointment.bay_id == bay_id)
    if status_filter is not None:
        query = query.where(Appointment.status == status_filter.value)
    if customer_id is not None:
        query = query.where(Appointment.customer_id == customer_id)
    if vehicle_id is not None:
        query = query.where(Appointment.vehicle_id == vehicle_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    appointments = db.scalars(
        query.order_by(Appointment.start_time.asc(), Appointment.id.asc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return AppointmentListResponse(
        items=[_appointment_to_read(db, auth, appointment) for appointment in appointments],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(appointments) < total,
    )


def get_availability(
    *,
    db: Session,
    auth: AuthContext,
    technician_id: int,
    date_from: datetime,
    date_to: datetime,
    bay_id: int | None = None,
) -> AvailabilityResponse:
    _validate_technician(db, auth, technician_id)
    if bay_id is not None:
        _validate_bay(db, auth, bay_id)
    date_from = ensure_utc(date_from)
    date_to = ensure_utc(date_to)
    if date_to <= date_from:
        raise SchedulingStoreError("date_to must be later than date_from.")

    working_windows: list[AvailabilityWindow] = []
    cursor_local = date_from.astimezone(SHOP_TIMEZONE)
    end_local = date_to.astimezone(SHOP_TIMEZONE)
    day_cursor = cursor_local.replace(hour=0, minute=0, second=0, microsecond=0)
    while day_cursor < end_local:
        day_rows = db.scalars(
            select(WorkingHours).where(
                WorkingHours.owner_user_id == effective_owner_id(auth),
                WorkingHours.technician_id == technician_id,
                WorkingHours.day_of_week == day_cursor.weekday(),
            )
        ).all()
        for row in day_rows:
            window_start = (day_cursor + timedelta(minutes=row.start_minute)).astimezone(UTC)
            window_end = (day_cursor + timedelta(minutes=row.end_minute)).astimezone(UTC)
            if window_end > date_from and window_start < date_to:
                working_windows.append(
                    AvailabilityWindow(
                        start_time=max(window_start, date_from),
                        end_time=min(window_end, date_to),
                    )
                )
        day_cursor += timedelta(days=1)

    busy_rows = db.scalars(
        select(Appointment).where(
            Appointment.owner_user_id == effective_owner_id(auth),
            Appointment.technician_id == technician_id,
            Appointment.status.in_([status.value for status in _ACTIVE_STATUSES]),
            Appointment.start_time < date_to,
            Appointment.end_time > date_from,
        )
    ).all()
    busy_windows = [
        AvailabilityWindow(
            start_time=ensure_utc(row.start_time) - timedelta(minutes=row.travel_buffer_minutes),
            end_time=ensure_utc(row.end_time) + timedelta(minutes=row.travel_buffer_minutes),
        )
        for row in busy_rows
    ]

    applicability_clauses = [
        ScheduleBlock.technician_id == technician_id,
        and_(ScheduleBlock.technician_id.is_(None), ScheduleBlock.bay_id.is_(None)),
    ]
    if bay_id is not None:
        applicability_clauses.append(ScheduleBlock.bay_id == bay_id)
    block_rows = db.scalars(
        select(ScheduleBlock).where(
            ScheduleBlock.owner_user_id == effective_owner_id(auth),
            ScheduleBlock.start_time < date_to,
            ScheduleBlock.end_time > date_from,
            or_(*applicability_clauses),
        )
    ).all()
    blocked_windows = [
        AvailabilityWindow(start_time=ensure_utc(row.start_time), end_time=ensure_utc(row.end_time))
        for row in block_rows
    ]

    return AvailabilityResponse(
        technician_id=technician_id,
        bay_id=bay_id,
        date_from=date_from,
        date_to=date_to,
        working_windows=working_windows,
        busy_windows=busy_windows,
        blocked_windows=blocked_windows,
    )
