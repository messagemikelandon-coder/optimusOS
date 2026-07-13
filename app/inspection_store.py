from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id, ensure_utc
from app.config import Settings
from app.db_models import Inspection, Technician, Vehicle, WorkOrder
from app.models import (
    InspectionCreate,
    InspectionItem,
    InspectionListResponse,
    InspectionRead,
    InspectionUpdate,
)
from app.technician_store import display_name as technician_display_name
from app.vehicle_store import vehicle_display_name


class InspectionStoreError(ValueError):
    pass


class InspectionNotFoundError(InspectionStoreError):
    pass


def _owner_query(auth: AuthContext) -> Select[tuple[Inspection]]:
    return select(Inspection).where(Inspection.owner_user_id == effective_owner_id(auth))


def _get_inspection(db: Session, auth: AuthContext, inspection_id: int) -> Inspection:
    inspection = db.scalar(_owner_query(auth).where(Inspection.id == inspection_id))
    if inspection is None:
        raise InspectionNotFoundError("Inspection not found.")
    return inspection


def _validate_vehicle(db: Session, auth: AuthContext, vehicle_id: int) -> None:
    vehicle = db.scalar(
        select(Vehicle).where(
            Vehicle.id == vehicle_id, Vehicle.owner_user_id == effective_owner_id(auth)
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
            Technician.owner_user_id == effective_owner_id(auth),
        )
    )
    if technician is None:
        raise InspectionStoreError("Selected technician was not found.")


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
        raise InspectionStoreError("Selected work order was not found.")


def _items_to_dicts(items: list[InspectionItem]) -> list[dict[str, object]]:
    return [item.model_dump() for item in items]


def _to_read(db: Session, inspection: Inspection) -> InspectionRead:
    vehicle = db.get(Vehicle, inspection.vehicle_id)
    technician = db.get(Technician, inspection.technician_id) if inspection.technician_id else None
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
        created_at=ensure_utc(inspection.created_at),
        updated_at=ensure_utc(inspection.updated_at),
    )


def create_inspection(
    *, db: Session, auth: AuthContext, payload: InspectionCreate
) -> InspectionRead:
    _validate_vehicle(db, auth, payload.vehicle_id)
    _validate_technician(db, auth, payload.technician_id)
    _validate_work_order(db, auth, payload.work_order_id)
    inspection = Inspection(
        owner_user_id=effective_owner_id(auth),
        vehicle_id=payload.vehicle_id,
        work_order_id=payload.work_order_id,
        technician_id=payload.technician_id,
        inspection_type=payload.inspection_type,
        items=_items_to_dicts(payload.items),
        overall_notes=payload.overall_notes,
    )
    db.add(inspection)
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
        _validate_work_order(db, auth, payload.work_order_id)
        inspection.work_order_id = payload.work_order_id
    if "inspection_type" in fields_set:
        inspection.inspection_type = payload.inspection_type
    if "items" in fields_set and payload.items is not None:
        inspection.items = _items_to_dicts(payload.items)
    if "overall_notes" in fields_set:
        inspection.overall_notes = payload.overall_notes
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    return _to_read(db, inspection)


def delete_inspection(*, db: Session, auth: AuthContext, inspection_id: int) -> None:
    inspection = _get_inspection(db, auth, inspection_id)
    db.delete(inspection)
    db.commit()


def list_inspections(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    vehicle_id: int | None = None,
    work_order_id: int | None = None,
) -> InspectionListResponse:
    if page_size > settings.customers_max_page_size:
        raise InspectionStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise InspectionStoreError("Page must be 1 or greater.")

    query = _owner_query(auth)
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
