from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id, effective_shop_owner_id, ensure_utc
from app.config import Settings
from app.db_models import Inspection, InspectionEvent, Technician, Vehicle, WorkOrder
from app.models import (
    InspectionArchiveResponse,
    InspectionCreate,
    InspectionEventRead,
    InspectionEventsResponse,
    InspectionItem,
    InspectionListResponse,
    InspectionRead,
    InspectionUpdate,
)
from app.shop_store import resolve_shop_id
from app.technician_store import display_name as technician_display_name
from app.technician_store import get_technician_for_user
from app.vehicle_store import vehicle_display_name


class InspectionStoreError(ValueError):
    pass


class InspectionNotFoundError(InspectionStoreError):
    pass


def _owner_query(db: Session, auth: AuthContext) -> Select[tuple[Inspection]]:
    query = select(Inspection).where(Inspection.shop_id == effective_shop_id(db, auth))
    if auth.user.role == "technician":
        # Same pattern as work_order_store._work_order_query: a technician
        # only sees inspections tied to one of their own assigned work
        # orders, not every inspection for the shop -- do not rely on the
        # inspection's own (client-settable) technician_id field for this
        # boundary.
        technician = get_technician_for_user(db, auth)
        if technician is None:
            return query.where(Inspection.id.is_(None))
        assigned_work_order_ids = select(WorkOrder.id).where(
            WorkOrder.assigned_technician_id == technician.id
        )
        query = query.where(Inspection.work_order_id.in_(assigned_work_order_ids))
    return query


def _get_inspection(db: Session, auth: AuthContext, inspection_id: int) -> Inspection:
    inspection = db.scalar(_owner_query(db, auth).where(Inspection.id == inspection_id))
    if inspection is None:
        raise InspectionNotFoundError("Inspection not found.")
    return inspection


def _validate_vehicle(db: Session, auth: AuthContext, vehicle_id: int) -> None:
    vehicle = db.scalar(
        select(Vehicle).where(
            Vehicle.id == vehicle_id, Vehicle.shop_id == effective_shop_id(db, auth)
        )
    )
    if vehicle is None:
        raise InspectionStoreError("Selected vehicle was not found.")


def _validate_technician(db: Session, auth: AuthContext, technician_id: int | None) -> None:
    if technician_id is None:
        return
    technician = db.scalar(
        select(Technician).where(
            Technician.id == technician_id,
            Technician.shop_id == effective_shop_id(db, auth),
        )
    )
    if technician is None:
        raise InspectionStoreError("Selected technician was not found.")


def _validate_work_order(
    db: Session,
    auth: AuthContext,
    work_order_id: int | None,
    *,
    vehicle_id: int | None = None,
) -> None:
    if auth.user.role == "technician" and work_order_id is None:
        raise InspectionStoreError(
            "Technicians must link an inspection to their own assigned work order."
        )
    if work_order_id is None:
        return
    work_order = db.scalar(
        select(WorkOrder).where(
            WorkOrder.id == work_order_id,
            WorkOrder.shop_id == effective_shop_id(db, auth),
        )
    )
    if work_order is None:
        raise InspectionStoreError("Selected work order was not found.")
    if auth.user.role == "technician":
        technician = get_technician_for_user(db, auth)
        if technician is None or work_order.assigned_technician_id != technician.id:
            raise InspectionStoreError("Selected work order is not assigned to you.")
        if vehicle_id is not None and work_order.vehicle_id != vehicle_id:
            raise InspectionStoreError(
                "Selected vehicle does not match the linked work order's vehicle."
            )


def _items_to_dicts(items: list[InspectionItem]) -> list[dict[str, object]]:
    return [item.model_dump() for item in items]


def _to_read(db: Session, inspection: Inspection) -> InspectionRead:
    vehicle = db.scalar(
        select(Vehicle).where(
            Vehicle.id == inspection.vehicle_id,
            Vehicle.shop_id == inspection.shop_id,
        )
    )
    technician = (
        db.scalar(
            select(Technician).where(
                Technician.id == inspection.technician_id,
                Technician.shop_id == inspection.shop_id,
            )
        )
        if inspection.technician_id
        else None
    )
    items = [InspectionItem.model_validate(item) for item in inspection.items]
    return InspectionRead(
        id=inspection.id,
        vehicle_id=inspection.vehicle_id,
        work_order_id=inspection.work_order_id,
        technician_id=inspection.technician_id,
        inspection_type=inspection.inspection_type,
        items=items,
        overall_notes=inspection.overall_notes,
        vehicle_display_name=vehicle_display_name(vehicle) if vehicle else None,
        technician_display_name=technician_display_name(technician) if technician else None,
        has_attention_items=any(item.status == "attention" for item in items),
        has_failed_items=any(item.status == "fail" for item in items),
        is_archived=inspection.is_archived,
        archived_at=ensure_utc(inspection.archived_at) if inspection.archived_at else None,
        created_at=ensure_utc(inspection.created_at),
        updated_at=ensure_utc(inspection.updated_at),
    )


def _record_event(db: Session, inspection: Inspection, auth: AuthContext, event_type: str) -> None:
    db.add(
        InspectionEvent(
            inspection_id=inspection.id,
            owner_user_id=inspection.owner_user_id,
            shop_id=inspection.shop_id,
            event_type=event_type,
            actor_type=auth.user.role,
            actor_user_id=auth.user.id,
            actor_name=auth.user.display_name,
        )
    )


def create_inspection(
    *, db: Session, auth: AuthContext, payload: InspectionCreate
) -> InspectionRead:
    _validate_vehicle(db, auth, payload.vehicle_id)
    _validate_technician(db, auth, payload.technician_id)
    _validate_work_order(db, auth, payload.work_order_id, vehicle_id=payload.vehicle_id)
    inspection = Inspection(
        owner_user_id=effective_shop_owner_id(db, auth),
        shop_id=resolve_shop_id(db, auth),
        vehicle_id=payload.vehicle_id,
        work_order_id=payload.work_order_id,
        technician_id=payload.technician_id,
        inspection_type=payload.inspection_type,
        items=_items_to_dicts(payload.items),
        overall_notes=payload.overall_notes,
        created_by_user_id=auth.user.id,
        updated_by_user_id=auth.user.id,
    )
    db.add(inspection)
    db.flush()
    _record_event(db, inspection, auth, "created")
    db.commit()
    db.refresh(inspection)
    return _to_read(db, inspection)


def get_inspection(*, db: Session, auth: AuthContext, inspection_id: int) -> InspectionRead:
    return _to_read(db, _get_inspection(db, auth, inspection_id))


def update_inspection(
    *,
    db: Session,
    auth: AuthContext,
    inspection_id: int,
    payload: InspectionUpdate,
) -> InspectionRead:
    inspection = _get_inspection(db, auth, inspection_id)
    fields_set = payload.model_fields_set
    if "technician_id" in fields_set:
        _validate_technician(db, auth, payload.technician_id)
        inspection.technician_id = payload.technician_id
    if "work_order_id" in fields_set:
        _validate_work_order(db, auth, payload.work_order_id, vehicle_id=inspection.vehicle_id)
        inspection.work_order_id = payload.work_order_id
    if "inspection_type" in fields_set:
        inspection.inspection_type = payload.inspection_type
    if "items" in fields_set and payload.items is not None:
        inspection.items = _items_to_dicts(payload.items)
    if "overall_notes" in fields_set:
        inspection.overall_notes = payload.overall_notes
    if fields_set:
        inspection.updated_by_user_id = auth.user.id
        db.add(inspection)
        _record_event(db, inspection, auth, "updated")
        db.commit()
        db.refresh(inspection)
    return _to_read(db, inspection)


def archive_inspection(
    *, db: Session, auth: AuthContext, inspection_id: int
) -> InspectionArchiveResponse:
    inspection = _get_inspection(db, auth, inspection_id)
    if not inspection.is_archived:
        inspection.is_archived = True
        inspection.archived_at = datetime.now(UTC)
        inspection.archived_by_user_id = auth.user.id
        db.add(inspection)
        _record_event(db, inspection, auth, "archived")
        db.commit()
        db.refresh(inspection)
    return InspectionArchiveResponse(inspection=_to_read(db, inspection))


def list_inspection_events(
    *, db: Session, auth: AuthContext, inspection_id: int
) -> InspectionEventsResponse:
    inspection = _get_inspection(db, auth, inspection_id)
    events = db.scalars(
        select(InspectionEvent)
        .where(
            InspectionEvent.inspection_id == inspection.id,
            InspectionEvent.shop_id == inspection.shop_id,
        )
        .order_by(InspectionEvent.created_at.asc(), InspectionEvent.id.asc())
    ).all()
    return InspectionEventsResponse(
        inspection_id=inspection.id,
        events=[
            InspectionEventRead(
                id=event.id,
                event_type=event.event_type,
                actor_type=event.actor_type,
                actor_name=event.actor_name,
                created_at=ensure_utc(event.created_at),
            )
            for event in events
        ],
    )


def list_inspections(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    vehicle_id: int | None = None,
    work_order_id: int | None = None,
    archived: bool = False,
) -> InspectionListResponse:
    if page_size > settings.customers_max_page_size:
        raise InspectionStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise InspectionStoreError("Page must be 1 or greater.")

    query = _owner_query(db, auth).where(Inspection.is_archived == archived)
    if vehicle_id is not None:
        query = query.where(Inspection.vehicle_id == vehicle_id)
    if work_order_id is not None:
        query = query.where(Inspection.work_order_id == work_order_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    inspections = db.scalars(
        query.order_by(Inspection.created_at.desc(), Inspection.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return InspectionListResponse(
        items=[_to_read(db, inspection) for inspection in inspections],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(inspections) < total,
    )
