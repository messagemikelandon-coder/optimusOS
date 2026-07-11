from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id, ensure_utc
from app.config import Settings
from app.customer_store import display_name as customer_display_name
from app.db_models import Estimate, WorkOrder, WorkOrderNote, WorkOrderStatusEvent
from app.estimate_store import EstimateNotFoundError, _revision_to_read
from app.invoice_store import ensure_draft_invoice_for_work_order
from app.models import (
    EstimatePaymentOptionCode,
    EstimateRevisionRead,
    EstimateStatus,
    InvoiceStatus,
    NotificationEntityType,
    NotificationEvent,
    WorkOrderListResponse,
    WorkOrderNoteCreate,
    WorkOrderNoteRead,
    WorkOrderNoteVisibility,
    WorkOrderRead,
    WorkOrderStatus,
    WorkOrderStatusEventRead,
    WorkOrderStatusUpdate,
    WorkOrderUpdate,
)
from app.notification_store import record_notification
from app.vehicle_store import vehicle_display_name

PAYMENT_PLAN_OPTIONS = {
    EstimatePaymentOptionCode.SPLIT_PAYMENT.value,
    EstimatePaymentOptionCode.TWO_MONTH_PLAN.value,
}

TRANSITIONS: dict[WorkOrderStatus, tuple[WorkOrderStatus, ...]] = {
    WorkOrderStatus.PENDING_REQUIREMENTS: (
        WorkOrderStatus.READY_TO_SCHEDULE,
        WorkOrderStatus.CANCELLED,
    ),
    WorkOrderStatus.READY_TO_SCHEDULE: (
        WorkOrderStatus.SCHEDULED,
        WorkOrderStatus.CANCELLED,
    ),
    WorkOrderStatus.SCHEDULED: (
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.CANCELLED,
    ),
    WorkOrderStatus.IN_PROGRESS: (
        WorkOrderStatus.WAITING_FOR_PARTS,
        WorkOrderStatus.COMPLETED,
        WorkOrderStatus.CANCELLED,
    ),
    WorkOrderStatus.WAITING_FOR_PARTS: (
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.CANCELLED,
    ),
    WorkOrderStatus.WAITING_FOR_APPROVAL: (),
    WorkOrderStatus.COMPLETED: (),
    WorkOrderStatus.CANCELLED: (),
}


class WorkOrderStoreError(ValueError):
    pass


class WorkOrderNotFoundError(WorkOrderStoreError):
    pass


def _work_order_query(auth: AuthContext) -> Select[tuple[WorkOrder]]:
    return select(WorkOrder).where(WorkOrder.owner_user_id == effective_owner_id(auth))


def _require_work_order(db: Session, auth: AuthContext, work_order_id: int) -> WorkOrder:
    work_order = db.scalar(_work_order_query(auth).where(WorkOrder.id == work_order_id))
    if work_order is None:
        raise WorkOrderNotFoundError("Work order not found.")
    return work_order


def _require_approved_estimate(db: Session, auth: AuthContext, estimate_id: int) -> Estimate:
    estimate = db.scalar(
        select(Estimate).where(
            Estimate.owner_user_id == effective_owner_id(auth), Estimate.id == estimate_id
        )
    )
    if estimate is None:
        raise EstimateNotFoundError("Estimate not found.")
    if (
        estimate.status != EstimateStatus.APPROVED.value
        or estimate.approved_revision_number is None
    ):
        raise WorkOrderStoreError("Only approved estimates can be converted to work orders.")
    return estimate


def _approved_revision(estimate: Estimate):
    revision = next(
        (
            item
            for item in estimate.revisions
            if item.revision_number == estimate.approved_revision_number
        ),
        None,
    )
    if revision is None:
        raise WorkOrderStoreError("Approved estimate revision is unavailable.")
    return revision


def _is_payment_plan(work_order: WorkOrder) -> bool:
    return (work_order.payment_option_selected or "") in PAYMENT_PLAN_OPTIONS


def _ready_requirements_met(work_order: WorkOrder) -> bool:
    if not _is_payment_plan(work_order):
        return True
    return work_order.deposit_received and work_order.authorization_confirmed


def _allowed_next_statuses(work_order: WorkOrder) -> list[WorkOrderStatus]:
    statuses = list(TRANSITIONS[WorkOrderStatus(work_order.status)])
    if WorkOrderStatus(
        work_order.status
    ) == WorkOrderStatus.PENDING_REQUIREMENTS and not _ready_requirements_met(work_order):
        return [status for status in statuses if status != WorkOrderStatus.READY_TO_SCHEDULE]
    return statuses


def _blocked_transitions(work_order: WorkOrder) -> dict[str, str]:
    blocked: dict[str, str] = {}
    if WorkOrderStatus(
        work_order.status
    ) == WorkOrderStatus.PENDING_REQUIREMENTS and not _ready_requirements_met(work_order):
        blocked[WorkOrderStatus.READY_TO_SCHEDULE.value] = (
            "Payment-plan work orders require both deposit received and authorization "
            "confirmed before scheduling."
        )
    return blocked


def _status_event_to_read(event: WorkOrderStatusEvent) -> WorkOrderStatusEventRead:
    return WorkOrderStatusEventRead(
        id=event.id,
        from_status=WorkOrderStatus(event.from_status) if event.from_status else None,
        to_status=WorkOrderStatus(event.to_status),
        reason=event.reason,
        created_by_user_id=event.created_by_user_id,
        created_by_display_name=None,
        created_at=ensure_utc(event.created_at),
    )


def _note_to_read(note: WorkOrderNote) -> WorkOrderNoteRead:
    return WorkOrderNoteRead(
        id=note.id,
        visibility=WorkOrderNoteVisibility(note.visibility),
        note=note.note,
        created_by_user_id=note.created_by_user_id,
        created_by_display_name=None,
        created_at=ensure_utc(note.created_at),
    )


def _to_read(work_order: WorkOrder) -> WorkOrderRead:
    revision: EstimateRevisionRead = _revision_to_read(work_order.revision)
    return WorkOrderRead(
        id=work_order.id,
        estimate_id=work_order.estimate_id,
        estimate_revision_id=work_order.estimate_revision_id,
        estimate_number=work_order.estimate_number,
        customer_id=work_order.customer_id,
        vehicle_id=work_order.vehicle_id,
        customer_display_name=customer_display_name(work_order.customer),
        vehicle_display_name=vehicle_display_name(work_order.vehicle),
        title=work_order.title,
        complaint=work_order.complaint,
        diagnosis=work_order.diagnosis,
        status=WorkOrderStatus(work_order.status),
        estimate_total=work_order.estimate_total,
        labor_hours_estimate=work_order.labor_hours_estimate,
        payment_option_selected=work_order.payment_option_selected,
        invoice_id=work_order.invoice.id if work_order.invoice else None,
        invoice_number=work_order.invoice.invoice_number if work_order.invoice else None,
        invoice_status=InvoiceStatus(work_order.invoice.status) if work_order.invoice else None,
        deposit_received=work_order.deposit_received,
        authorization_confirmed=work_order.authorization_confirmed,
        scheduled_for=ensure_utc(work_order.scheduled_for) if work_order.scheduled_for else None,
        allowed_next_statuses=_allowed_next_statuses(work_order),
        blocked_transitions=_blocked_transitions(work_order),
        source_revision=revision,
        status_history=[_status_event_to_read(event) for event in work_order.status_events],
        notes=[_note_to_read(note) for note in work_order.notes],
        created_at=ensure_utc(work_order.created_at),
        updated_at=ensure_utc(work_order.updated_at),
    )


def _append_status_event(
    *,
    db: Session,
    work_order: WorkOrder,
    from_status: WorkOrderStatus | None,
    to_status: WorkOrderStatus,
    reason: str | None,
    auth: AuthContext,
) -> None:
    db.add(
        WorkOrderStatusEvent(
            work_order_id=work_order.id,
            owner_user_id=effective_owner_id(auth),
            from_status=from_status.value if from_status else None,
            to_status=to_status.value,
            reason=reason,
            created_by_user_id=auth.user.id,
        )
    )


def create_work_order_from_estimate(
    *,
    db: Session,
    auth: AuthContext,
    estimate_id: int,
) -> WorkOrderRead:
    estimate = _require_approved_estimate(db, auth, estimate_id)
    revision = _approved_revision(estimate)
    existing = db.scalar(
        _work_order_query(auth).where(
            WorkOrder.estimate_id == estimate.id,
            WorkOrder.estimate_revision_id == revision.id,
        )
    )
    if existing is not None:
        return _to_read(existing)

    revision_read = _revision_to_read(revision)
    payment_option_selected = estimate.payment_option_selected
    initial_status = (
        WorkOrderStatus.PENDING_REQUIREMENTS
        if (payment_option_selected or "") in PAYMENT_PLAN_OPTIONS
        else WorkOrderStatus.READY_TO_SCHEDULE
    )
    work_order = WorkOrder(
        owner_user_id=effective_owner_id(auth),
        estimate_id=estimate.id,
        estimate_revision_id=revision.id,
        customer_id=estimate.customer_id,
        vehicle_id=estimate.vehicle_id,
        estimate_number=estimate.estimate_number,
        title=revision_read.request.job,
        complaint=revision_read.request.job,
        diagnosis=None,
        status=initial_status.value,
        estimate_total=estimate.estimate_total,
        labor_hours_estimate=revision_read.estimate.totals.labor_hours,
        payment_option_selected=payment_option_selected,
        deposit_received=False,
        authorization_confirmed=False,
    )
    db.add(work_order)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            _work_order_query(auth).where(
                WorkOrder.estimate_id == estimate.id,
                WorkOrder.estimate_revision_id == revision.id,
            )
        )
        if existing is None:
            raise
        return _to_read(existing)
    _append_status_event(
        db=db,
        work_order=work_order,
        from_status=None,
        to_status=initial_status,
        reason="Created from approved estimate revision.",
        auth=auth,
    )
    db.commit()
    db.refresh(work_order)
    return _to_read(work_order)


def list_work_orders(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    status: WorkOrderStatus | None,
    search: str | None,
    customer_id: int | None,
    vehicle_id: int | None,
) -> WorkOrderListResponse:
    if page_size > settings.work_orders_max_page_size:
        raise WorkOrderStoreError(
            f"Page size exceeds the maximum of {settings.work_orders_max_page_size}."
        )
    if page < 1:
        raise WorkOrderStoreError("Page must be 1 or greater.")
    query = _work_order_query(auth)
    if status is not None:
        query = query.where(WorkOrder.status == status.value)
    if customer_id is not None:
        query = query.where(WorkOrder.customer_id == customer_id)
    if vehicle_id is not None:
        query = query.where(WorkOrder.vehicle_id == vehicle_id)
    if search:
        token = search.strip().lower()
        if token:
            query = query.where(
                or_(
                    func.lower(WorkOrder.estimate_number).contains(token),
                    func.lower(WorkOrder.title).contains(token),
                )
            )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    items = db.scalars(
        query.order_by(WorkOrder.updated_at.desc(), WorkOrder.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return WorkOrderListResponse(
        items=[_to_read(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(items) < total,
    )


def get_work_order(*, db: Session, auth: AuthContext, work_order_id: int) -> WorkOrderRead:
    return _to_read(_require_work_order(db, auth, work_order_id))


def update_work_order(
    *,
    db: Session,
    auth: AuthContext,
    work_order_id: int,
    payload: WorkOrderUpdate,
) -> WorkOrderRead:
    work_order = _require_work_order(db, auth, work_order_id)
    if payload.diagnosis is not None or "diagnosis" in payload.model_fields_set:
        work_order.diagnosis = payload.diagnosis
    if payload.scheduled_for is not None or "scheduled_for" in payload.model_fields_set:
        work_order.scheduled_for = payload.scheduled_for
    if payload.deposit_received is not None or "deposit_received" in payload.model_fields_set:
        work_order.deposit_received = bool(payload.deposit_received)
    if (
        payload.authorization_confirmed is not None
        or "authorization_confirmed" in payload.model_fields_set
    ):
        work_order.authorization_confirmed = bool(payload.authorization_confirmed)
    db.add(work_order)
    db.commit()
    db.refresh(work_order)
    return _to_read(work_order)


def transition_work_order_status(
    *,
    db: Session,
    auth: AuthContext,
    work_order_id: int,
    payload: WorkOrderStatusUpdate,
) -> WorkOrderRead:
    work_order = _require_work_order(db, auth, work_order_id)
    current_status = WorkOrderStatus(work_order.status)
    target_status = payload.status
    if target_status == WorkOrderStatus.WAITING_FOR_APPROVAL:
        raise WorkOrderStoreError("Change-order approval routing is not implemented yet.")
    if target_status == current_status:
        return _to_read(work_order)
    if target_status not in TRANSITIONS[current_status]:
        raise WorkOrderStoreError(
            f"Cannot transition work order from {current_status.value} to {target_status.value}."
        )
    if (
        current_status == WorkOrderStatus.PENDING_REQUIREMENTS
        and target_status == WorkOrderStatus.READY_TO_SCHEDULE
        and not _ready_requirements_met(work_order)
    ):
        raise WorkOrderStoreError(
            "Payment-plan work orders require both deposit received and authorization "
            "confirmed before scheduling."
        )
    work_order.status = target_status.value
    db.add(work_order)
    _append_status_event(
        db=db,
        work_order=work_order,
        from_status=current_status,
        to_status=target_status,
        reason=payload.reason,
        auth=auth,
    )
    # Staged before the COMPLETED branch below so it rides (and rolls back
    # with) the same transaction that ensure_draft_invoice_for_work_order
    # commits internally.
    record_notification(
        db=db,
        owner_user_id=work_order.owner_user_id,
        entity_type=NotificationEntityType.WORK_ORDER,
        entity_id=work_order.id,
        event=NotificationEvent.WORK_ORDER_STATUS_CHANGED,
        title=(
            f"Work order {work_order.estimate_number}: "
            f"{current_status.value} → {target_status.value}"
        ),
        body=payload.reason,
    )
    try:
        if target_status is WorkOrderStatus.COMPLETED:
            ensure_draft_invoice_for_work_order(db=db, auth=auth, work_order=work_order)
            db.refresh(work_order)
            return _to_read(work_order)
        db.commit()
        db.refresh(work_order)
        return _to_read(work_order)
    except Exception:
        db.rollback()
        raise


def add_work_order_note(
    *,
    db: Session,
    auth: AuthContext,
    work_order_id: int,
    payload: WorkOrderNoteCreate,
) -> WorkOrderRead:
    work_order = _require_work_order(db, auth, work_order_id)
    db.add(
        WorkOrderNote(
            work_order_id=work_order.id,
            owner_user_id=effective_owner_id(auth),
            visibility=payload.visibility.value,
            note=payload.note,
            created_by_user_id=auth.user.id,
        )
    )
    # Notes are part of work-order execution activity, so refresh the parent
    # record's recency for list ordering.
    work_order.updated_at = datetime.now(UTC)
    db.add(work_order)
    db.commit()
    db.refresh(work_order)
    return _to_read(work_order)
