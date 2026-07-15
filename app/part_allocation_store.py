from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id, ensure_utc
from app.db_models import Part, PartAllocation, PartAllocationEvent, WorkOrder
from app.models import (
    PartAllocationAllocateRequest,
    PartAllocationCreate,
    PartAllocationEventRead,
    PartAllocationEventsResponse,
    PartAllocationListResponse,
    PartAllocationRead,
    PartAllocationReturnRequest,
    PartAllocationUseRequest,
)
from app.technician_store import get_technician_for_user


class PartAllocationStoreError(ValueError):
    pass


class PartAllocationNotFoundError(PartAllocationStoreError):
    pass


def _owner_query(db: Session, auth: AuthContext) -> Select[tuple[PartAllocation]]:
    query = select(PartAllocation).where(PartAllocation.owner_user_id == effective_owner_id(auth))
    if auth.user.role == "technician":
        # Same pattern as work_order_store._work_order_query and Phase 6 Part
        # E's diagnostics/inspections carve-out: a technician only sees
        # allocations tied to one of their own assigned work orders.
        technician = get_technician_for_user(db, auth.user.id)
        if technician is None:
            return query.where(PartAllocation.id.is_(None))
        assigned_work_order_ids = select(WorkOrder.id).where(
            WorkOrder.assigned_technician_id == technician.id
        )
        query = query.where(PartAllocation.work_order_id.in_(assigned_work_order_ids))
    return query


def _get_allocation(db: Session, auth: AuthContext, allocation_id: int) -> PartAllocation:
    allocation = db.scalar(_owner_query(db, auth).where(PartAllocation.id == allocation_id))
    if allocation is None:
        raise PartAllocationNotFoundError("Part allocation not found.")
    return allocation


def _validate_work_order_access(db: Session, auth: AuthContext, work_order_id: int) -> WorkOrder:
    work_order = db.scalar(
        select(WorkOrder).where(
            WorkOrder.id == work_order_id,
            WorkOrder.owner_user_id == effective_owner_id(auth),
        )
    )
    if work_order is None:
        raise PartAllocationStoreError("Selected work order was not found.")
    if auth.user.role == "technician":
        technician = get_technician_for_user(db, auth.user.id)
        if technician is None or work_order.assigned_technician_id != technician.id:
            raise PartAllocationStoreError("Selected work order is not assigned to you.")
    return work_order


def _require_part(db: Session, auth: AuthContext, part_id: int) -> Part:
    part = db.scalar(
        select(Part).where(Part.id == part_id, Part.owner_user_id == effective_owner_id(auth))
    )
    if part is None:
        raise PartAllocationStoreError("Selected part was not found.")
    return part


def _to_read(allocation: PartAllocation) -> PartAllocationRead:
    return PartAllocationRead(
        id=allocation.id,
        work_order_id=allocation.work_order_id,
        part_id=allocation.part_id,
        part_number=allocation.part.part_number,
        part_description=allocation.part.description,
        quantity_required=allocation.quantity_required,
        quantity_allocated=allocation.quantity_allocated,
        quantity_used=allocation.quantity_used,
        quantity_returned=allocation.quantity_returned,
        unit_cost_snapshot=float(allocation.unit_cost_snapshot)
        if allocation.unit_cost_snapshot is not None
        else None,
        created_at=ensure_utc(allocation.created_at),
        updated_at=ensure_utc(allocation.updated_at),
    )


def _record_event(
    db: Session,
    allocation: PartAllocation,
    auth: AuthContext,
    *,
    event_type: str,
    quantity_delta: int,
    inventory_override: bool = False,
    override_reason: str | None = None,
) -> None:
    db.add(
        PartAllocationEvent(
            allocation_id=allocation.id,
            owner_user_id=allocation.owner_user_id,
            event_type=event_type,
            quantity_delta=quantity_delta,
            actor_type=auth.user.role,
            actor_user_id=auth.user.id,
            actor_name=auth.user.display_name,
            inventory_override=inventory_override,
            override_reason=override_reason if inventory_override else None,
        )
    )


def create_part_allocation(
    *, db: Session, auth: AuthContext, work_order_id: int, payload: PartAllocationCreate
) -> PartAllocationRead:
    _validate_work_order_access(db, auth, work_order_id)
    part = _require_part(db, auth, payload.part_id)
    if part.is_archived:
        raise PartAllocationStoreError(
            f"Part {part.part_number} is archived and cannot be allocated."
        )
    allocation = PartAllocation(
        owner_user_id=effective_owner_id(auth),
        work_order_id=work_order_id,
        part_id=payload.part_id,
        quantity_required=payload.quantity_required,
        unit_cost_snapshot=part.unit_cost,
        created_by_user_id=auth.user.id,
    )
    db.add(allocation)
    db.commit()
    db.refresh(allocation)
    return _to_read(allocation)


def get_part_allocation(
    *, db: Session, auth: AuthContext, allocation_id: int
) -> PartAllocationRead:
    return _to_read(_get_allocation(db, auth, allocation_id))


def list_part_allocations(
    *, db: Session, auth: AuthContext, work_order_id: int
) -> PartAllocationListResponse:
    _validate_work_order_access(db, auth, work_order_id)
    allocations = db.scalars(
        _owner_query(db, auth)
        .where(PartAllocation.work_order_id == work_order_id)
        .order_by(PartAllocation.created_at.asc(), PartAllocation.id.asc())
    ).all()
    return PartAllocationListResponse(items=[_to_read(item) for item in allocations])


def allocate_part(
    *, db: Session, auth: AuthContext, allocation_id: int, payload: PartAllocationAllocateRequest
) -> PartAllocationRead:
    allocation = _get_allocation(db, auth, allocation_id)

    # Lock the allocation and its part, then reload both with
    # populate_existing so every attribute read below reflects the
    # post-lock state -- see Phase 6 Part F's purchase-order receiving fix
    # for why a plain id-only `.with_for_update()` is not sufficient here:
    # it does not refresh an already-loaded ORM object's other attributes
    # in SQLAlchemy's identity map, which would let a concurrent request
    # read stale pre-lock quantities despite correctly holding the lock.
    allocation = db.scalar(
        select(PartAllocation)
        .where(PartAllocation.id == allocation.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert allocation is not None
    part = db.scalar(
        select(Part)
        .where(Part.id == allocation.part_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert part is not None

    available = part.quantity_on_hand
    inventory_override = False
    if payload.quantity > available:
        if not payload.override:
            raise PartAllocationStoreError(
                f"Cannot allocate {payload.quantity} units; only {available} on hand. "
                "Check the override to allocate anyway."
            )
        if not payload.override_reason:
            raise PartAllocationStoreError(
                "An override reason is required to allocate more than the available inventory."
            )
        inventory_override = True
        part.quantity_on_hand = 0
    else:
        part.quantity_on_hand = available - payload.quantity

    allocation.quantity_allocated += payload.quantity
    db.add(allocation)
    db.add(part)
    _record_event(
        db,
        allocation,
        auth,
        event_type="allocated",
        quantity_delta=payload.quantity,
        inventory_override=inventory_override,
        override_reason=payload.override_reason,
    )
    db.commit()
    db.refresh(allocation)
    return _to_read(allocation)


def use_part_allocation(
    *, db: Session, auth: AuthContext, allocation_id: int, payload: PartAllocationUseRequest
) -> PartAllocationRead:
    allocation = _get_allocation(db, auth, allocation_id)
    allocation = db.scalar(
        select(PartAllocation)
        .where(PartAllocation.id == allocation.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert allocation is not None

    available_to_use = allocation.quantity_allocated - allocation.quantity_used
    if payload.quantity > available_to_use:
        raise PartAllocationStoreError(
            f"Cannot mark {payload.quantity} units used; only {available_to_use} allocated "
            "and not yet used."
        )
    allocation.quantity_used += payload.quantity
    db.add(allocation)
    _record_event(db, allocation, auth, event_type="used", quantity_delta=payload.quantity)
    db.commit()
    db.refresh(allocation)
    return _to_read(allocation)


def return_part_allocation(
    *, db: Session, auth: AuthContext, allocation_id: int, payload: PartAllocationReturnRequest
) -> PartAllocationRead:
    allocation = _get_allocation(db, auth, allocation_id)
    allocation = db.scalar(
        select(PartAllocation)
        .where(PartAllocation.id == allocation.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert allocation is not None
    part = db.scalar(
        select(Part)
        .where(Part.id == allocation.part_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert part is not None

    returnable = (
        allocation.quantity_allocated - allocation.quantity_used - allocation.quantity_returned
    )
    if payload.quantity > returnable:
        raise PartAllocationStoreError(
            f"Cannot return {payload.quantity} units; only {returnable} allocated-but-unused "
            "and not already returned."
        )
    allocation.quantity_returned += payload.quantity
    part.quantity_on_hand += payload.quantity
    db.add(allocation)
    db.add(part)
    _record_event(db, allocation, auth, event_type="returned", quantity_delta=payload.quantity)
    db.commit()
    db.refresh(allocation)
    return _to_read(allocation)


def list_part_allocation_events(
    *, db: Session, auth: AuthContext, allocation_id: int
) -> PartAllocationEventsResponse:
    allocation = _get_allocation(db, auth, allocation_id)
    events = db.scalars(
        select(PartAllocationEvent)
        .where(PartAllocationEvent.allocation_id == allocation.id)
        .order_by(PartAllocationEvent.created_at.asc(), PartAllocationEvent.id.asc())
    ).all()
    return PartAllocationEventsResponse(
        allocation_id=allocation.id,
        events=[
            PartAllocationEventRead(
                id=event.id,
                event_type=event.event_type,
                quantity_delta=event.quantity_delta,
                actor_type=event.actor_type,
                actor_name=event.actor_name,
                inventory_override=event.inventory_override,
                override_reason=event.override_reason,
                created_at=ensure_utc(event.created_at),
            )
            for event in events
        ],
    )
