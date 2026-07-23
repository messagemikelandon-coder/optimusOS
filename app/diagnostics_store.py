from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id, effective_shop_owner_id, ensure_utc
from app.config import Settings
from app.db_models import DiagnosticFinding, DiagnosticFindingEvent, Technician, Vehicle, WorkOrder
from app.models import (
    DiagnosticConfidence,
    DiagnosticFindingArchiveResponse,
    DiagnosticFindingCreate,
    DiagnosticFindingEventRead,
    DiagnosticFindingEventsResponse,
    DiagnosticFindingListResponse,
    DiagnosticFindingRead,
    DiagnosticFindingUpdate,
    DiagnosticSeverity,
)
from app.shop_store import resolve_shop_id
from app.technician_store import display_name as technician_display_name
from app.technician_store import get_technician_for_user
from app.vehicle_store import vehicle_display_name


class DiagnosticsStoreError(ValueError):
    pass


class DiagnosticFindingNotFoundError(DiagnosticsStoreError):
    pass


def _owner_query(db: Session, auth: AuthContext) -> Select[tuple[DiagnosticFinding]]:
    query = select(DiagnosticFinding).where(
        DiagnosticFinding.shop_id == effective_shop_id(db, auth)
    )
    if auth.user.role == "technician":
        # Same pattern as work_order_store._work_order_query: a technician
        # only sees findings tied to one of their own assigned work orders,
        # not every finding for the shop -- do not rely on the finding's own
        # (client-settable) technician_id field for this boundary.
        technician = get_technician_for_user(db, auth)
        if technician is None:
            return query.where(DiagnosticFinding.id.is_(None))
        assigned_work_order_ids = select(WorkOrder.id).where(
            WorkOrder.assigned_technician_id == technician.id
        )
        query = query.where(DiagnosticFinding.work_order_id.in_(assigned_work_order_ids))
    return query


def _diagnosis_is_unverified(conclusion: str | None, confidence: object | None) -> bool:
    """Evidence-integrity signal for the Diagnostic Evidence Engine: a conclusion
    (final diagnosis) that carries no confidence level is an *unverified* working
    theory, not an established fact. Callers (the read model and the UI) use this
    to ensure such a diagnosis is always presented as unverified and never stated
    as fact. Returns ``False`` when there is no conclusion at all (nothing is
    being asserted) or when a confidence level is on record."""
    return bool(conclusion) and confidence is None


def _get_finding(db: Session, auth: AuthContext, finding_id: int) -> DiagnosticFinding:
    finding = db.scalar(_owner_query(db, auth).where(DiagnosticFinding.id == finding_id))
    if finding is None:
        raise DiagnosticFindingNotFoundError("Diagnostic finding not found.")
    return finding


def _validate_vehicle(db: Session, auth: AuthContext, vehicle_id: int) -> None:
    vehicle = db.scalar(
        select(Vehicle).where(
            Vehicle.id == vehicle_id, Vehicle.shop_id == effective_shop_id(db, auth)
        )
    )
    if vehicle is None:
        raise DiagnosticsStoreError("Selected vehicle was not found.")


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
        raise DiagnosticsStoreError("Selected technician was not found.")


def _validate_work_order(
    db: Session,
    auth: AuthContext,
    work_order_id: int | None,
    *,
    vehicle_id: int | None = None,
) -> None:
    if auth.user.role == "technician" and work_order_id is None:
        raise DiagnosticsStoreError(
            "Technicians must link a finding to their own assigned work order."
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
        raise DiagnosticsStoreError("Selected work order was not found.")
    if auth.user.role == "technician":
        technician = get_technician_for_user(db, auth)
        if technician is None or work_order.assigned_technician_id != technician.id:
            raise DiagnosticsStoreError("Selected work order is not assigned to you.")
        if vehicle_id is not None and work_order.vehicle_id != vehicle_id:
            raise DiagnosticsStoreError(
                "Selected vehicle does not match the linked work order's vehicle."
            )


def _to_read(db: Session, finding: DiagnosticFinding) -> DiagnosticFindingRead:
    vehicle = db.scalar(
        select(Vehicle).where(Vehicle.id == finding.vehicle_id, Vehicle.shop_id == finding.shop_id)
    )
    technician = (
        db.scalar(
            select(Technician).where(
                Technician.id == finding.technician_id,
                Technician.shop_id == finding.shop_id,
            )
        )
        if finding.technician_id
        else None
    )
    return DiagnosticFindingRead(
        id=finding.id,
        vehicle_id=finding.vehicle_id,
        work_order_id=finding.work_order_id,
        technician_id=finding.technician_id,
        codes=finding.codes,
        complaint=finding.complaint,
        symptoms=finding.symptoms,
        tests_performed=finding.tests_performed,
        confidence=DiagnosticConfidence(finding.confidence) if finding.confidence else None,
        severity=DiagnosticSeverity(finding.severity) if finding.severity else None,
        recommended_next_test=finding.recommended_next_test,
        conclusion=finding.conclusion,
        diagnosis_unverified=_diagnosis_is_unverified(finding.conclusion, finding.confidence),
        vehicle_display_name=vehicle_display_name(vehicle) if vehicle else None,
        technician_display_name=technician_display_name(technician) if technician else None,
        is_archived=finding.is_archived,
        archived_at=ensure_utc(finding.archived_at) if finding.archived_at else None,
        created_at=ensure_utc(finding.created_at),
        updated_at=ensure_utc(finding.updated_at),
    )


def _record_event(
    db: Session, finding: DiagnosticFinding, auth: AuthContext, event_type: str
) -> None:
    db.add(
        DiagnosticFindingEvent(
            finding_id=finding.id,
            owner_user_id=finding.owner_user_id,
            shop_id=finding.shop_id,
            event_type=event_type,
            actor_type=auth.user.role,
            actor_user_id=auth.user.id,
            actor_name=auth.user.display_name,
        )
    )


def create_diagnostic_finding(
    *, db: Session, auth: AuthContext, payload: DiagnosticFindingCreate
) -> DiagnosticFindingRead:
    _validate_vehicle(db, auth, payload.vehicle_id)
    _validate_technician(db, auth, payload.technician_id)
    _validate_work_order(db, auth, payload.work_order_id, vehicle_id=payload.vehicle_id)
    finding = DiagnosticFinding(
        owner_user_id=effective_shop_owner_id(db, auth),
        shop_id=resolve_shop_id(db, auth),
        vehicle_id=payload.vehicle_id,
        work_order_id=payload.work_order_id,
        technician_id=payload.technician_id,
        codes=payload.codes,
        complaint=payload.complaint,
        symptoms=payload.symptoms,
        tests_performed=payload.tests_performed,
        confidence=payload.confidence.value if payload.confidence else None,
        severity=payload.severity.value if payload.severity else None,
        recommended_next_test=payload.recommended_next_test,
        conclusion=payload.conclusion,
        created_by_user_id=auth.user.id,
        updated_by_user_id=auth.user.id,
    )
    db.add(finding)
    db.flush()
    _record_event(db, finding, auth, "created")
    db.commit()
    db.refresh(finding)
    return _to_read(db, finding)


def get_diagnostic_finding(
    *, db: Session, auth: AuthContext, finding_id: int
) -> DiagnosticFindingRead:
    return _to_read(db, _get_finding(db, auth, finding_id))


def update_diagnostic_finding(
    *,
    db: Session,
    auth: AuthContext,
    finding_id: int,
    payload: DiagnosticFindingUpdate,
) -> DiagnosticFindingRead:
    finding = _get_finding(db, auth, finding_id)
    fields_set = payload.model_fields_set
    if "technician_id" in fields_set:
        _validate_technician(db, auth, payload.technician_id)
        finding.technician_id = payload.technician_id
    if "work_order_id" in fields_set:
        _validate_work_order(db, auth, payload.work_order_id, vehicle_id=finding.vehicle_id)
        finding.work_order_id = payload.work_order_id
    if "codes" in fields_set:
        finding.codes = payload.codes
    if "complaint" in fields_set:
        finding.complaint = payload.complaint
    if "symptoms" in fields_set and payload.symptoms is not None:
        finding.symptoms = payload.symptoms
    if "tests_performed" in fields_set:
        finding.tests_performed = payload.tests_performed
    if "confidence" in fields_set:
        finding.confidence = payload.confidence.value if payload.confidence else None
    if "severity" in fields_set:
        finding.severity = payload.severity.value if payload.severity else None
    if "recommended_next_test" in fields_set:
        finding.recommended_next_test = payload.recommended_next_test
    if "conclusion" in fields_set:
        finding.conclusion = payload.conclusion
    if fields_set:
        finding.updated_by_user_id = auth.user.id
        db.add(finding)
        _record_event(db, finding, auth, "updated")
        db.commit()
        db.refresh(finding)
    return _to_read(db, finding)


def archive_diagnostic_finding(
    *, db: Session, auth: AuthContext, finding_id: int
) -> DiagnosticFindingArchiveResponse:
    finding = _get_finding(db, auth, finding_id)
    if not finding.is_archived:
        finding.is_archived = True
        finding.archived_at = datetime.now(UTC)
        finding.archived_by_user_id = auth.user.id
        db.add(finding)
        _record_event(db, finding, auth, "archived")
        db.commit()
        db.refresh(finding)
    return DiagnosticFindingArchiveResponse(finding=_to_read(db, finding))


def list_diagnostic_finding_events(
    *, db: Session, auth: AuthContext, finding_id: int
) -> DiagnosticFindingEventsResponse:
    finding = _get_finding(db, auth, finding_id)
    events = db.scalars(
        select(DiagnosticFindingEvent)
        .where(
            DiagnosticFindingEvent.finding_id == finding.id,
            DiagnosticFindingEvent.shop_id == finding.shop_id,
        )
        .order_by(DiagnosticFindingEvent.created_at.asc(), DiagnosticFindingEvent.id.asc())
    ).all()
    return DiagnosticFindingEventsResponse(
        finding_id=finding.id,
        events=[
            DiagnosticFindingEventRead(
                id=event.id,
                event_type=event.event_type,
                actor_type=event.actor_type,
                actor_name=event.actor_name,
                created_at=ensure_utc(event.created_at),
            )
            for event in events
        ],
    )


def list_diagnostic_findings(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    vehicle_id: int | None = None,
    work_order_id: int | None = None,
    archived: bool = False,
) -> DiagnosticFindingListResponse:
    if page_size > settings.customers_max_page_size:
        raise DiagnosticsStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise DiagnosticsStoreError("Page must be 1 or greater.")

    query = _owner_query(db, auth).where(DiagnosticFinding.is_archived == archived)
    if vehicle_id is not None:
        query = query.where(DiagnosticFinding.vehicle_id == vehicle_id)
    if work_order_id is not None:
        query = query.where(DiagnosticFinding.work_order_id == work_order_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    findings = db.scalars(
        query.order_by(DiagnosticFinding.created_at.desc(), DiagnosticFinding.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return DiagnosticFindingListResponse(
        items=[_to_read(db, finding) for finding in findings],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(findings) < total,
    )
