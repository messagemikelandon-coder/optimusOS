from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id
from app.db_models import JobCompilation, JobCompilationEvent
from app.estimate_store import create_estimate_from_payload, get_estimate
from app.job_compiler import JobCompilationNotFoundError
from app.job_compiler import _to_read as _compiled_job_to_read
from app.models import (
    Availability,
    CompiledJobLaborLine,
    CompiledJobPartLine,
    CompiledJobTotals,
    Confidence,
    DecodedVehicle,
    EstimateFeeItem,
    EstimateLaborItem,
    EstimateRequest,
    EstimateResponse,
    EstimateTotals,
    JobCompilationReleaseResponse,
    JobCompilationStatus,
    LaborResearch,
    PartRequirement,
    PartsResearch,
    ResearchBundle,
    ResolvedLocation,
    SelectedPart,
)
from app.vehicle_store import get_vehicle_model, vehicle_display_name

# A finding's diagnostic confidence maps deterministically onto the estimate
# research confidence scale, preserving the evidence signal into the estimate.
_CONFIDENCE_MAP = {
    "theory": Confidence.LOW,
    "probable": Confidence.MEDIUM,
    "confirmed": Confidence.HIGH,
}


class JobReleaseError(ValueError):
    pass


def _build_estimate_response(compilation: JobCompilation, vehicle) -> EstimateResponse:  # type: ignore[no-untyped-def]
    """Deterministically build a canonical ``EstimateResponse`` from a compiled
    job's stored snapshot. Preserves labor, customer-priced parts (never
    supplier cost), totals, and the source finding's confidence/severity/
    conclusion into the estimate's research bundle. No OpenAI/paid call."""
    totals = CompiledJobTotals.model_validate(compilation.totals)
    labor_lines = [CompiledJobLaborLine.model_validate(line) for line in compilation.labor_lines]
    part_lines = [CompiledJobPartLine.model_validate(line) for line in compilation.part_lines]
    labor_items = [
        EstimateLaborItem(
            description=line.title,
            labor_hours=line.labor_hours,
            labor_rate=line.labor_rate,
            labor_total=line.labor_total,
        )
        for line in labor_lines
    ]
    selected_parts = [
        SelectedPart(
            part_name=line.description,
            quantity=line.quantity,
            retailer="In-house catalog",
            brand=None,
            part_number=line.part_number,
            unit_price=line.unit_price,
            extended_price=line.extended_price,
            availability=Availability.UNKNOWN,
            store_name=None,
            url=None,
            confidence=Confidence.HIGH,
        )
        for line in part_lines
    ]
    fee_items: list[EstimateFeeItem] = []
    if totals.shop_supplies > 0:
        fee_items.append(
            EstimateFeeItem(
                code="shop_supplies", label="Shop supplies", amount=totals.shop_supplies
            )
        )
    if totals.parts_tax > 0:
        fee_items.append(
            EstimateFeeItem(code="parts_tax", label="Parts tax", amount=totals.parts_tax)
        )

    labor_hours = totals.labor_hours
    estimate_totals = EstimateTotals(
        labor_hours=labor_hours,
        labor_rate=totals.labor_rate,
        labor_total=totals.labor_total,
        parts_subtotal=totals.parts_subtotal,
        shop_supplies=totals.shop_supplies,
        mobile_service_fee=0.0,
        parts_tax=totals.parts_tax,
        estimated_total=totals.estimated_total,
        practical_time_low=min(labor_hours, 300.0),
        practical_time_high=min(labor_hours, 300.0),
    )

    confidence = _CONFIDENCE_MAP.get(compilation.source_confidence or "", Confidence.LOW)
    severity = compilation.source_severity
    warnings: list[str] = []
    risk_flags: list[str] = []
    if severity == "unsafe":
        warnings.append(
            "Safety-critical: the source diagnostic finding is marked unsafe. Do not release "
            "the vehicle until this work is completed."
        )
        risk_flags.append("Source finding severity: unsafe")
    elif severity == "service_soon":
        risk_flags.append("Source finding severity: service soon")
    if compilation.source_diagnosis_unverified:
        warnings.append(
            "The source diagnosis was recorded as an unverified working theory (no confidence "
            "level). Confirm before customer release."
        )

    research = ResearchBundle(
        labor=LaborResearch(
            book_hours=min(labor_hours, 200.0),
            practical_hours_low=min(labor_hours, 300.0),
            practical_hours_high=min(labor_hours, 300.0),
            confidence=confidence,
            basis=(
                f"Deterministically compiled from job compilation #{compilation.id} "
                f"(revision {compilation.revision_number}) of diagnostic finding "
                f"#{compilation.finding_id}. Labor and customer parts pricing are shop-entered; "
                "no external research or AI was used."
            ),
            special_tools=[],
            risk_flags=risk_flags,
        ),
        parts=PartsResearch(
            requirements=[
                PartRequirement(
                    part_name=line.description,
                    quantity=line.quantity,
                    required=True,
                )
                for line in part_lines
            ],
            notes=[],
        ),
        summary=(
            f"Deterministic job compiled from diagnostic finding #{compilation.finding_id}"
            + (f": {compilation.source_conclusion}" if compilation.source_conclusion else ".")
        ),
        citations=[],
        warnings=warnings,
    )

    return EstimateResponse(
        vehicle=DecodedVehicle(
            vin=vehicle.vin,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            trim=vehicle.trim,
            engine=vehicle.engine,
            drivetrain=vehicle.drivetrain,
        ),
        location=ResolvedLocation(),
        job=_job_text(compilation, vehicle),
        research=research,
        labor_items=labor_items,
        selected_parts=selected_parts,
        fee_items=fee_items,
        totals=estimate_totals,
        approval_required=True,
        approval_reason="Compiled deterministically; owner must review before customer release.",
        generated_at_utc=datetime.now(UTC).isoformat(),
    )


def _job_text(compilation: JobCompilation, vehicle) -> str:  # type: ignore[no-untyped-def]
    label = vehicle_display_name(vehicle) or "vehicle"
    conclusion = (compilation.source_conclusion or "compiled service").strip()
    text = f"{label}: {conclusion}"
    return text[:500]


def _build_estimate_request(compilation: JobCompilation, vehicle) -> EstimateRequest:  # type: ignore[no-untyped-def]
    # The canonical vehicle (make+model, possibly no year/VIN) is carried by the
    # response's DecodedVehicle and estimate.vehicle_id; the request's vehicle is
    # redundant metadata and is omitted rather than forced through VehicleInput's
    # stricter require-vin-or-year+make+model rule (which a make+model-only
    # vehicle cannot satisfy).
    return EstimateRequest(
        vehicle=None,
        job=_job_text(compilation, vehicle),
        location=None,
        labor_rate=float(compilation.labor_rate),
        mobile_service_fee=None,
        shop_supplies_percent=None,
        parts_tax_rate=None,
    )


def release_job_compilation(
    *, db: Session, auth: AuthContext, compilation_id: int
) -> JobCompilationReleaseResponse:
    """Release an owner-reviewed draft compilation into a real canonical
    ``Estimate`` (DRAFT), reusing the estimate/approval/work-order/invoice
    pipeline. Owner/manager-gated (the release is the shop-side approval);
    customer approval before work-order activation remains the existing estimate
    approval flow. Idempotent on ``released_estimate_id``. Rejects a superseded
    (stale) compilation. Row-locked and committed in one transaction so no
    duplicate estimate/lines/events are ever created."""
    compilation = db.scalar(
        select(JobCompilation)
        .where(
            JobCompilation.id == compilation_id,
            JobCompilation.shop_id == effective_shop_id(db, auth),
        )
        .with_for_update()
    )
    if compilation is None:
        raise JobCompilationNotFoundError("Job compilation not found.")

    existing_estimate_id = compilation.released_estimate_id
    if existing_estimate_id is not None:
        # Idempotent: already released -> return the existing linked estimate
        # unchanged; never create a second estimate or event.
        return JobCompilationReleaseResponse(
            already_released=True,
            compilation=_compiled_job_to_read(db, compilation),
            estimate=get_estimate(db=db, auth=auth, estimate_id=existing_estimate_id),
        )

    if compilation.status != JobCompilationStatus.DRAFT.value:
        raise JobReleaseError(
            "Only the current draft compilation can be released; this revision has been superseded."
        )
    if not compilation.labor_lines and not compilation.part_lines:
        raise JobReleaseError("This compilation has no labor or parts to release.")

    vehicle = get_vehicle_model(db=db, auth=auth, vehicle_id=compilation.vehicle_id)
    request_model = _build_estimate_request(compilation, vehicle)
    response_model = _build_estimate_response(compilation, vehicle)

    estimate = create_estimate_from_payload(
        db=db,
        auth=auth,
        customer_id=vehicle.customer_id,
        vehicle_id=vehicle.id,
        request_model=request_model,
        response_model=response_model,
        commit=False,
    )

    compilation.released = True
    compilation.released_estimate_id = estimate.id
    compilation.released_at = datetime.now(UTC)
    compilation.released_by_user_id = auth.user.id
    compilation.updated_by_user_id = auth.user.id
    db.add(compilation)
    db.add(
        JobCompilationEvent(
            compilation_id=compilation.id,
            owner_user_id=compilation.owner_user_id,
            shop_id=compilation.shop_id,
            revision_number=compilation.revision_number,
            event_type="released",
            actor_type=auth.user.role,
            actor_user_id=auth.user.id,
            actor_name=auth.user.display_name,
        )
    )
    released_estimate_id = estimate.id
    db.commit()
    db.refresh(compilation)
    return JobCompilationReleaseResponse(
        already_released=False,
        compilation=_compiled_job_to_read(db, compilation),
        estimate=get_estimate(db=db, auth=auth, estimate_id=released_estimate_id),
    )
