from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id, ensure_utc
from app.config import Settings
from app.db_models import WorkflowGap, WorkflowGapEvent
from app.models import (
    WorkflowGapCreate,
    WorkflowGapEventRead,
    WorkflowGapEventsResponse,
    WorkflowGapListResponse,
    WorkflowGapRead,
    WorkflowGapSeverity,
    WorkflowGapStatus,
    WorkflowGapUpdate,
)


class WorkflowGapStoreError(ValueError):
    pass


class WorkflowGapNotFoundError(WorkflowGapStoreError):
    pass


class WorkflowGapConflictError(WorkflowGapStoreError):
    pass


_TRANSITIONS = {
    "open": {"investigating", "planned", "resolved", "wont_fix"},
    "investigating": {"open", "planned", "resolved", "wont_fix"},
    "planned": {"investigating", "resolved", "wont_fix"},
    "resolved": {"open"},
    "wont_fix": {"open"},
}


def _query(db: Session, auth: AuthContext) -> Select[tuple[WorkflowGap]]:
    return select(WorkflowGap).where(WorkflowGap.shop_id == effective_shop_id(db, auth))


def _get(
    db: Session, auth: AuthContext, workflow_gap_id: int, *, for_update: bool = False
) -> WorkflowGap:
    query = _query(db, auth).where(WorkflowGap.id == workflow_gap_id)
    if for_update:
        query = query.with_for_update()
    gap = db.scalar(query)
    if gap is None:
        raise WorkflowGapNotFoundError("Workflow gap not found.")
    return gap


def _to_read(gap: WorkflowGap) -> WorkflowGapRead:
    return WorkflowGapRead(
        id=gap.id,
        title=gap.title,
        description=gap.description,
        workflow_area=gap.workflow_area,
        severity=gap.severity,  # type: ignore[arg-type]
        status=gap.status,  # type: ignore[arg-type]
        workaround=gap.workaround,
        occurrence_count=gap.occurrence_count,
        created_by_user_account_id=gap.created_by_user_account_id,
        updated_by_user_account_id=gap.updated_by_user_account_id,
        first_reported_at=ensure_utc(gap.first_reported_at),
        last_reported_at=ensure_utc(gap.last_reported_at),
        closed_at=ensure_utc(gap.closed_at) if gap.closed_at else None,
        created_at=ensure_utc(gap.created_at),
        updated_at=ensure_utc(gap.updated_at),
    )


def _event(
    gap: WorkflowGap,
    auth: AuthContext,
    event_type: str,
    *,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict | None = None,
) -> WorkflowGapEvent:
    return WorkflowGapEvent(
        workflow_gap_id=gap.id,
        shop_id=gap.shop_id,
        actor_user_account_id=auth.user.id,
        actor_name=auth.user.display_name,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        event_metadata=metadata,
    )


def create_workflow_gap(
    db: Session, auth: AuthContext, payload: WorkflowGapCreate
) -> WorkflowGapRead:
    now = datetime.now(UTC)
    gap = WorkflowGap(
        shop_id=effective_shop_id(db, auth),
        created_by_user_account_id=auth.user.id,
        updated_by_user_account_id=auth.user.id,
        title=payload.title,
        description=payload.description,
        workflow_area=payload.workflow_area,
        severity=payload.severity.value,
        status="open",
        workaround=payload.workaround,
        first_reported_at=now,
        last_reported_at=now,
    )
    db.add(gap)
    db.flush()
    db.add(_event(gap, auth, "created", to_status="open"))
    db.commit()
    db.refresh(gap)
    return _to_read(gap)


def get_workflow_gap(db: Session, auth: AuthContext, workflow_gap_id: int) -> WorkflowGapRead:
    return _to_read(_get(db, auth, workflow_gap_id))


def update_workflow_gap(
    db: Session,
    auth: AuthContext,
    workflow_gap_id: int,
    payload: WorkflowGapUpdate,
) -> WorkflowGapRead:
    gap = _get(db, auth, workflow_gap_id, for_update=True)
    fields = payload.model_fields_set
    changed_fields: list[str] = []
    for field in ("title", "description", "workflow_area", "workaround"):
        if field in fields:
            value = getattr(payload, field)
            if field != "workaround" and value is None:
                continue
            setattr(gap, field, value)
            changed_fields.append(field)
    if "severity" in fields and payload.severity is not None:
        gap.severity = payload.severity.value
        changed_fields.append("severity")

    old_status = gap.status
    if "status" in fields and payload.status is not None and payload.status.value != old_status:
        new_status = payload.status.value
        if new_status not in _TRANSITIONS[old_status]:
            raise WorkflowGapConflictError(
                f"Workflow gap cannot move from {old_status} to {new_status}."
            )
        gap.status = new_status
        gap.closed_at = datetime.now(UTC) if new_status in {"resolved", "wont_fix"} else None
        db.add(
            _event(
                gap,
                auth,
                "status_changed",
                from_status=old_status,
                to_status=new_status,
            )
        )

    if not changed_fields and gap.status == old_status:
        raise WorkflowGapStoreError("No workflow-gap changes were supplied.")
    if changed_fields:
        db.add(_event(gap, auth, "updated", metadata={"fields": changed_fields}))
    gap.updated_by_user_account_id = auth.user.id
    db.add(gap)
    db.commit()
    db.refresh(gap)
    return _to_read(gap)


def record_workflow_gap_occurrence(
    db: Session, auth: AuthContext, workflow_gap_id: int
) -> WorkflowGapRead:
    gap = _get(db, auth, workflow_gap_id, for_update=True)
    if gap.status in {"resolved", "wont_fix"}:
        raise WorkflowGapConflictError("Reopen this workflow gap before recording an occurrence.")
    gap.occurrence_count += 1
    gap.last_reported_at = datetime.now(UTC)
    gap.updated_by_user_account_id = auth.user.id
    db.add(gap)
    db.add(
        _event(
            gap,
            auth,
            "occurrence_recorded",
            metadata={"occurrence_count": gap.occurrence_count},
        )
    )
    db.commit()
    db.refresh(gap)
    return _to_read(gap)


def list_workflow_gaps(
    db: Session,
    auth: AuthContext,
    settings: Settings,
    *,
    page: int,
    page_size: int,
    status_filter: WorkflowGapStatus | None,
    severity_filter: WorkflowGapSeverity | None,
    search: str | None,
) -> WorkflowGapListResponse:
    if page < 1 or page_size < 1:
        raise WorkflowGapStoreError("Page and page size must be 1 or greater.")
    if page_size > settings.customers_max_page_size:
        raise WorkflowGapStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    query = _query(db, auth)
    if status_filter:
        query = query.where(WorkflowGap.status == status_filter.value)
    if severity_filter:
        query = query.where(WorkflowGap.severity == severity_filter.value)
    if search:
        for token in [part for part in search.strip().lower().split() if part]:
            query = query.where(
                or_(
                    func.lower(WorkflowGap.title).contains(token),
                    func.lower(WorkflowGap.description).contains(token),
                    func.lower(WorkflowGap.workflow_area).contains(token),
                )
            )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    items = db.scalars(
        query.order_by(WorkflowGap.updated_at.desc(), WorkflowGap.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return WorkflowGapListResponse(
        items=[_to_read(gap) for gap in items],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(items) < total,
    )


def list_workflow_gap_events(
    db: Session, auth: AuthContext, workflow_gap_id: int
) -> WorkflowGapEventsResponse:
    gap = _get(db, auth, workflow_gap_id)
    events = db.scalars(
        select(WorkflowGapEvent)
        .where(
            WorkflowGapEvent.workflow_gap_id == gap.id,
            WorkflowGapEvent.shop_id == gap.shop_id,
        )
        .order_by(WorkflowGapEvent.created_at, WorkflowGapEvent.id)
    ).all()
    return WorkflowGapEventsResponse(
        items=[
            WorkflowGapEventRead(
                id=event.id,
                event_type=event.event_type,  # type: ignore[arg-type]
                actor_user_account_id=event.actor_user_account_id,
                actor_name=event.actor_name,
                from_status=event.from_status,  # type: ignore[arg-type]
                to_status=event.to_status,  # type: ignore[arg-type]
                event_metadata=event.event_metadata,
                created_at=ensure_utc(event.created_at),
            )
            for event in events
        ]
    )
