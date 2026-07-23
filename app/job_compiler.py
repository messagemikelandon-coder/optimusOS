from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id, effective_shop_owner_id, ensure_utc
from app.config import Settings
from app.db_models import (
    DiagnosticFinding,
    JobCompilation,
    JobCompilationEvent,
    Part,
    Vehicle,
)
from app.diagnostics_store import _diagnosis_is_unverified
from app.models import (
    CompiledJobEventRead,
    CompiledJobEventsResponse,
    CompiledJobLaborLine,
    CompiledJobListResponse,
    CompiledJobPartLine,
    CompiledJobRead,
    CompiledJobTask,
    CompiledJobTotals,
    DiagnosticConfidence,
    DiagnosticSeverity,
    JobCompilationRequest,
    JobCompilationStatus,
)
from app.shop_store import resolve_shop_id
from app.vehicle_store import vehicle_display_name

MONEY = Decimal("0.01")
HOURS = Decimal("0.01")


class JobCompilerError(ValueError):
    pass


class CompilableFindingNotFoundError(JobCompilerError):
    pass


class JobCompilationNotFoundError(JobCompilerError):
    pass


def _money(value: float | Decimal) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise JobCompilerError("Job compilation failed: an amount was not a valid number.") from exc
    if not normalized.is_finite() or normalized < 0:
        raise JobCompilerError("Job compilation failed: an amount was negative or not finite.")
    return normalized.quantize(MONEY, rounding=ROUND_HALF_UP)


def _hours(value: float | Decimal) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise JobCompilerError("Job compilation failed: a labor-hour value was invalid.") from exc
    if not normalized.is_finite() or normalized <= 0:
        raise JobCompilerError("Job compilation failed: labor hours must be greater than zero.")
    return normalized.quantize(HOURS, rounding=ROUND_HALF_UP)


def _percent(value: float | None) -> Decimal:
    if value is None:
        return Decimal("0")
    normalized = Decimal(str(value))
    if not normalized.is_finite() or normalized < 0:
        raise JobCompilerError("Job compilation failed: a percentage was negative or not finite.")
    return normalized


def _get_compilable_finding(db: Session, auth: AuthContext, finding_id: int) -> DiagnosticFinding:
    """Load the finding to compile, shop-scoped and row-locked so concurrent
    compiles of the same finding serialize (preventing duplicate drafts). This
    endpoint is owner/manager-gated, so there is no technician read path here.

    Rejects an archived finding and one with no recorded ``conclusion`` -- a
    finding with no diagnosis on record is not an approved, compilable job. The
    owner initiating a compile is the shop-side approval to turn the diagnosis
    into recommended services; customer release remains a separate, later,
    explicitly gated step (this compiler never sends or approves anything)."""
    finding = db.scalar(
        select(DiagnosticFinding)
        .where(
            DiagnosticFinding.id == finding_id,
            DiagnosticFinding.shop_id == effective_shop_id(db, auth),
        )
        .with_for_update()
    )
    if finding is None:
        raise CompilableFindingNotFoundError("Diagnostic finding not found.")
    if finding.is_archived:
        raise JobCompilerError("An archived diagnostic finding cannot be compiled into a job.")
    if not finding.conclusion or not finding.conclusion.strip():
        raise JobCompilerError(
            "Only a diagnosed finding with a recorded conclusion can be compiled into a job."
        )
    return finding


def _compile_lines(
    db: Session,
    auth: AuthContext,
    payload: JobCompilationRequest,
) -> tuple[
    list[CompiledJobLaborLine],
    list[CompiledJobPartLine],
    list[CompiledJobTask],
    CompiledJobTotals,
    Decimal,
]:
    """Pure, deterministic expansion of the validated request into labor lines,
    aggregated part needs (priced from the catalog's customer ``unit_price``
    only -- supplier ``unit_cost``/markup is never read here), work-order task
    descriptors, and reconciled totals. No OpenAI/paid call."""
    labor_rate = _money(payload.labor_rate)
    if labor_rate <= 0:
        raise JobCompilerError("Job compilation failed: labor rate must be greater than zero.")

    labor_lines: list[CompiledJobLaborLine] = []
    tasks: list[CompiledJobTask] = []
    total_labor_hours = Decimal("0")
    total_labor = Decimal("0.00")
    part_quantities: dict[int, int] = {}
    part_order: list[int] = []

    for index, service in enumerate(payload.services, start=1):
        hours = _hours(service.labor_hours)
        line_total = _money(hours * labor_rate)
        if line_total <= 0:
            raise JobCompilerError(
                "Job compilation failed: each service must have positive labor value."
            )
        labor_lines.append(
            CompiledJobLaborLine(
                title=service.title,
                notes=service.notes,
                labor_hours=float(hours),
                labor_rate=float(labor_rate),
                labor_total=float(line_total),
            )
        )
        tasks.append(
            CompiledJobTask(
                sequence=index,
                title=service.title,
                notes=service.notes,
                labor_hours=float(hours),
            )
        )
        total_labor_hours += hours
        total_labor += line_total
        for part_input in service.parts:
            if part_input.part_id not in part_quantities:
                part_quantities[part_input.part_id] = 0
                part_order.append(part_input.part_id)
            part_quantities[part_input.part_id] += part_input.quantity

    part_lines: list[CompiledJobPartLine] = []
    parts_subtotal = Decimal("0.00")
    for part_id in part_order:
        part = db.scalar(
            select(Part).where(
                Part.id == part_id,
                Part.shop_id == effective_shop_id(db, auth),
            )
        )
        if part is None:
            raise JobCompilerError(f"Part {part_id} was not found for this shop.")
        if part.is_archived:
            raise JobCompilerError(
                f"Part {part.part_number} is archived and cannot be added to a job."
            )
        if part.unit_price is None:
            raise JobCompilerError(
                f"Part {part.part_number} has no customer price set; set a unit price before "
                "compiling it into a job."
            )
        unit_price = _money(part.unit_price)  # customer price only; unit_cost is never read
        quantity = part_quantities[part_id]
        extended = _money(unit_price * Decimal(quantity))
        part_lines.append(
            CompiledJobPartLine(
                part_id=part.id,
                part_number=part.part_number,
                description=part.description,
                quantity=quantity,
                unit_price=float(unit_price),
                extended_price=float(extended),
            )
        )
        parts_subtotal += extended

    shop_supplies = _money(total_labor * _percent(payload.shop_supplies_percent) / Decimal("100"))
    parts_tax = _money(parts_subtotal * _percent(payload.parts_tax_rate) / Decimal("100"))
    estimated_total = _money(total_labor + parts_subtotal + shop_supplies + parts_tax)
    if estimated_total <= 0:
        raise JobCompilerError(
            "Job compilation failed: the estimated total must be greater than zero."
        )

    totals = CompiledJobTotals(
        labor_hours=float(total_labor_hours),
        labor_rate=float(labor_rate),
        labor_total=float(total_labor),
        parts_subtotal=float(parts_subtotal),
        shop_supplies=float(shop_supplies),
        parts_tax=float(parts_tax),
        estimated_total=float(estimated_total),
    )
    return labor_lines, part_lines, tasks, totals, labor_rate


def _content_hash(
    finding: DiagnosticFinding,
    labor_lines: list[CompiledJobLaborLine],
    part_lines: list[CompiledJobPartLine],
    totals: CompiledJobTotals,
) -> str:
    """Deterministic idempotency key over the *computed, reconciled output* plus
    the source finding's evidence snapshot -- not the raw request inputs. Hashing
    the resolved labor lines, part lines (which carry the catalog customer
    ``unit_price`` and extended price at compile time), and totals means that
    *anything* affecting the output changes the hash: a changed labor rate/hours,
    a changed service list, a changed fee, and -- critically -- a changed catalog
    part price. Recompiling with an identical resolved output against an
    unchanged diagnosis is a true no-op; if a part's customer price is corrected
    in the catalog, the recompiled output differs and a fresh revision is
    created (the prior draft is never silently returned with stale pricing)."""
    canonical = {
        "finding_id": finding.id,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "conclusion": finding.conclusion,
        "labor_lines": [line.model_dump(mode="json") for line in labor_lines],
        "part_lines": [line.model_dump(mode="json") for line in part_lines],
        "totals": totals.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _record_event(
    db: Session,
    compilation: JobCompilation,
    auth: AuthContext,
    event_type: str,
    revision_number: int,
) -> None:
    db.add(
        JobCompilationEvent(
            compilation_id=compilation.id,
            owner_user_id=compilation.owner_user_id,
            shop_id=compilation.shop_id,
            revision_number=revision_number,
            event_type=event_type,
            actor_type=auth.user.role,
            actor_user_id=auth.user.id,
            actor_name=auth.user.display_name,
        )
    )


def _to_read(db: Session, compilation: JobCompilation) -> CompiledJobRead:
    vehicle = db.scalar(
        select(Vehicle).where(
            Vehicle.id == compilation.vehicle_id,
            Vehicle.shop_id == compilation.shop_id,
        )
    )
    return CompiledJobRead(
        id=compilation.id,
        finding_id=compilation.finding_id,
        vehicle_id=compilation.vehicle_id,
        status=JobCompilationStatus(compilation.status),
        revision_number=compilation.revision_number,
        released=compilation.released,
        content_hash=compilation.content_hash,
        source_severity=(
            DiagnosticSeverity(compilation.source_severity) if compilation.source_severity else None
        ),
        source_confidence=(
            DiagnosticConfidence(compilation.source_confidence)
            if compilation.source_confidence
            else None
        ),
        source_conclusion=compilation.source_conclusion,
        source_diagnosis_unverified=compilation.source_diagnosis_unverified,
        vehicle_display_name=vehicle_display_name(vehicle) if vehicle else None,
        labor_rate=float(compilation.labor_rate),
        labor_lines=[CompiledJobLaborLine.model_validate(line) for line in compilation.labor_lines],
        part_lines=[CompiledJobPartLine.model_validate(line) for line in compilation.part_lines],
        tasks=[CompiledJobTask.model_validate(task) for task in compilation.tasks],
        totals=CompiledJobTotals.model_validate(compilation.totals),
        superseded_by_id=compilation.superseded_by_id,
        released_estimate_id=compilation.released_estimate_id,
        created_at=ensure_utc(compilation.created_at),
        updated_at=ensure_utc(compilation.updated_at),
    )


def compile_job(
    *,
    db: Session,
    auth: AuthContext,
    finding_id: int,
    payload: JobCompilationRequest,
) -> CompiledJobRead:
    """Deterministically compile an approved diagnostic finding into a priced
    draft job. Idempotent: recompiling with identical inputs against an
    unchanged diagnosis returns the existing draft unchanged. Changed inputs
    supersede the prior draft and create the next revision. Never sends,
    approves, orders parts, alters customer records, or takes payment."""
    finding = _get_compilable_finding(db, auth, finding_id)
    labor_lines, part_lines, tasks, totals, labor_rate = _compile_lines(db, auth, payload)
    content_hash = _content_hash(finding, labor_lines, part_lines, totals)
    diagnosis_unverified = _diagnosis_is_unverified(finding.conclusion, finding.confidence)

    existing = db.scalar(
        select(JobCompilation).where(
            JobCompilation.finding_id == finding.id,
            JobCompilation.shop_id == finding.shop_id,
            JobCompilation.status == JobCompilationStatus.DRAFT.value,
        )
    )
    if existing is not None and existing.content_hash == content_hash:
        # Idempotent no-op: identical inputs + unchanged diagnosis. No new
        # revision, no duplicate lines/tasks, no new event.
        return _to_read(db, existing)

    revision_number = existing.revision_number + 1 if existing is not None else 1
    compilation = JobCompilation(
        owner_user_id=effective_shop_owner_id(db, auth),
        shop_id=resolve_shop_id(db, auth),
        finding_id=finding.id,
        vehicle_id=finding.vehicle_id,
        status=JobCompilationStatus.DRAFT.value,
        revision_number=revision_number,
        content_hash=content_hash,
        released=False,
        source_severity=finding.severity,
        source_confidence=finding.confidence,
        source_conclusion=finding.conclusion,
        source_diagnosis_unverified=diagnosis_unverified,
        labor_rate=labor_rate,
        labor_lines=[line.model_dump(mode="json") for line in labor_lines],
        part_lines=[line.model_dump(mode="json") for line in part_lines],
        tasks=[task.model_dump(mode="json") for task in tasks],
        totals=totals.model_dump(mode="json"),
        created_by_user_id=auth.user.id,
        updated_by_user_id=auth.user.id,
    )
    db.add(compilation)
    db.flush()
    if existing is not None:
        existing.status = JobCompilationStatus.SUPERSEDED.value
        existing.superseded_by_id = compilation.id
        existing.updated_by_user_id = auth.user.id
        db.add(existing)
        _record_event(db, existing, auth, "superseded", existing.revision_number)
        _record_event(db, compilation, auth, "recompiled", revision_number)
    else:
        _record_event(db, compilation, auth, "compiled", revision_number)
    db.commit()
    db.refresh(compilation)
    return _to_read(db, compilation)


def _require_compilation(db: Session, auth: AuthContext, compilation_id: int) -> JobCompilation:
    compilation = db.scalar(
        select(JobCompilation).where(
            JobCompilation.id == compilation_id,
            JobCompilation.shop_id == effective_shop_id(db, auth),
        )
    )
    if compilation is None:
        raise JobCompilationNotFoundError("Job compilation not found.")
    return compilation


def get_compiled_job(*, db: Session, auth: AuthContext, compilation_id: int) -> CompiledJobRead:
    return _to_read(db, _require_compilation(db, auth, compilation_id))


def list_compiled_jobs(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    finding_id: int | None = None,
    status: JobCompilationStatus | None = None,
    released: bool | None = None,
) -> CompiledJobListResponse:
    if page_size > settings.customers_max_page_size:
        raise JobCompilerError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise JobCompilerError("Page must be 1 or greater.")

    query = select(JobCompilation).where(JobCompilation.shop_id == effective_shop_id(db, auth))
    if finding_id is not None:
        query = query.where(JobCompilation.finding_id == finding_id)
    if status is not None:
        query = query.where(JobCompilation.status == status.value)
    if released is not None:
        query = query.where(JobCompilation.released == released)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    compilations = db.scalars(
        query.order_by(JobCompilation.updated_at.desc(), JobCompilation.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return CompiledJobListResponse(
        items=[_to_read(db, compilation) for compilation in compilations],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(compilations) < total,
    )


def list_compiled_job_events(
    *, db: Session, auth: AuthContext, compilation_id: int
) -> CompiledJobEventsResponse:
    compilation = _require_compilation(db, auth, compilation_id)
    events = db.scalars(
        select(JobCompilationEvent)
        .where(
            JobCompilationEvent.compilation_id == compilation.id,
            JobCompilationEvent.shop_id == compilation.shop_id,
        )
        .order_by(JobCompilationEvent.created_at.asc(), JobCompilationEvent.id.asc())
    ).all()
    return CompiledJobEventsResponse(
        compilation_id=compilation.id,
        events=[
            CompiledJobEventRead(
                id=event.id,
                event_type=event.event_type,
                actor_type=event.actor_type,
                actor_name=event.actor_name,
                revision_number=event.revision_number,
                created_at=ensure_utc(event.created_at),
            )
            for event in events
        ],
    )
