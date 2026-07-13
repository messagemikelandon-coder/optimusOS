from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id, ensure_utc
from app.customer_store import display_name as customer_display_name
from app.customer_store import get_customer_model
from app.db_models import (
    Estimate,
    EstimateApprovalEvent,
    EstimateApprovalRequest,
    EstimateRevision,
)
from app.models import (
    EstimateApprovalActionRequest,
    EstimateApprovalActionResponse,
    EstimateApprovalAuditResponse,
    EstimateApprovalEstimateView,
    EstimateApprovalEventRead,
    EstimateApprovalMethod,
    EstimateApprovalPublicView,
    EstimateApprovalResearchView,
    EstimateApprovalRevisionView,
    EstimateApprovalSendResponse,
    EstimateApprovalTokenRequest,
    EstimateCreate,
    EstimateCustomerSummary,
    EstimateDeclineActionRequest,
    EstimateListResponse,
    EstimatePaymentOption,
    EstimatePaymentOptionCode,
    EstimateRead,
    EstimateRecordBase,
    EstimateRequest,
    EstimateResponse,
    EstimateRevisionCreate,
    EstimateRevisionRead,
    EstimateSendForApprovalRequest,
    EstimateStatus,
    EstimateUpdate,
    EstimateVehicleSummary,
    NotificationEntityType,
    NotificationEvent,
    VehicleInput,
)
from app.notification_store import record_notification
from app.orchestrator import OptimusResearchOrchestrator
from app.vehicle_store import get_vehicle_model, vehicle_display_name

DEFAULT_ESTIMATE_TERMS = (
    "Approval authorizes the quoted work only. Additional material changes require a new revision. "
    "Parts-price deposits are due before parts are ordered."
)

DEFAULT_PAYMENT_OPTIONS = (
    EstimatePaymentOption(
        code=EstimatePaymentOptionCode.PAY_IN_FULL,
        label="Pay in full",
        description="Pay the full approved amount when service is complete.",
    ),
    EstimatePaymentOption(
        code=EstimatePaymentOptionCode.SPLIT_PAYMENT,
        label="Split payment",
        description="Pay a deposit now and the balance when service is complete.",
    ),
    EstimatePaymentOption(
        code=EstimatePaymentOptionCode.TWO_MONTH_PLAN,
        label="Two-month plan",
        description=(
            "Parts-price deposit is due before parts are ordered. No repair begins until the "
            "deposit and authorization are complete. Remaining payments are due 30 and 60 days "
            "after service."
        ),
        requires_payment_plan_acknowledgement=True,
    ),
)
MONEY = Decimal("0.01")


class EstimateStoreError(ValueError):
    pass


class EstimateNotFoundError(EstimateStoreError):
    pass


class EstimateApprovalTokenError(EstimateStoreError):
    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _canonical_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _default_payment_options() -> list[EstimatePaymentOption]:
    return [option.model_copy() for option in DEFAULT_PAYMENT_OPTIONS]


def _money(value: float | Decimal) -> Decimal:
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EstimateStoreError("Structured estimate generation failed.") from exc
    if not normalized.is_finite():
        raise EstimateStoreError("Structured estimate generation failed.")
    if normalized < 0:
        raise EstimateStoreError("Structured estimate generation failed.")
    return normalized.quantize(MONEY, rounding=ROUND_HALF_UP)


def _validate_generated_estimate(response_model: EstimateResponse) -> None:
    labor_items = response_model.labor_items
    selected_parts = response_model.selected_parts
    fee_map = {item.code: _money(item.amount) for item in response_model.fee_items}

    if not labor_items and not selected_parts:
        raise EstimateStoreError(
            "Structured estimate generation failed. Customer-facing labor or parts data is required."
        )

    recalculated_labor_hours = Decimal("0.0")
    recalculated_labor_total = Decimal("0.00")
    positive_labor_lines = 0
    for item in labor_items:
        labor_hours = Decimal(str(item.labor_hours))
        labor_rate = _money(item.labor_rate)
        labor_total = _money(item.labor_total)
        if labor_hours < 0:
            raise EstimateStoreError("Structured estimate generation failed.")
        if labor_hours > 0 and labor_total <= 0:
            raise EstimateStoreError("Structured estimate generation failed.")
        expected_labor_total = _money(labor_hours * labor_rate)
        if labor_total != expected_labor_total:
            raise EstimateStoreError(
                "Structured estimate generation failed. Labor totals did not reconcile."
            )
        recalculated_labor_hours += labor_hours
        recalculated_labor_total += labor_total
        if labor_total > 0:
            positive_labor_lines += 1

    recalculated_parts_subtotal = Decimal("0.00")
    for part in selected_parts:
        if part.quantity < 1:
            raise EstimateStoreError("Structured estimate generation failed.")
        unit_price = _money(part.unit_price)
        extended_price = _money(part.extended_price)
        expected_extended = _money(unit_price * Decimal(str(part.quantity)))
        if extended_price != expected_extended:
            raise EstimateStoreError(
                "Structured estimate generation failed. Part totals did not reconcile."
            )
        recalculated_parts_subtotal += extended_price

    required_parts = [
        requirement.part_name
        for requirement in response_model.research.parts.requirements
        if requirement.required
    ]
    if required_parts and not selected_parts:
        raise EstimateStoreError(
            "Structured estimate generation failed. Required customer-facing part pricing is missing."
        )

    expected_shop_supplies = fee_map.get("shop_supplies", Decimal("0.00"))
    expected_mobile_fee = fee_map.get("mobile_service_fee", Decimal("0.00"))
    expected_parts_tax = fee_map.get("parts_tax", Decimal("0.00"))
    additional_fees = sum(
        amount
        for code, amount in fee_map.items()
        if code not in {"shop_supplies", "mobile_service_fee", "parts_tax"}
    )
    totals = response_model.totals
    if _money(totals.labor_total) != recalculated_labor_total:
        raise EstimateStoreError("Structured estimate generation failed. Labor subtotal mismatch.")
    if _money(totals.parts_subtotal) != recalculated_parts_subtotal:
        raise EstimateStoreError("Structured estimate generation failed. Parts subtotal mismatch.")
    if _money(totals.shop_supplies) != expected_shop_supplies:
        raise EstimateStoreError(
            "Structured estimate generation failed. Fee totals did not reconcile."
        )
    if _money(totals.mobile_service_fee) != expected_mobile_fee:
        raise EstimateStoreError(
            "Structured estimate generation failed. Fee totals did not reconcile."
        )
    if _money(totals.parts_tax) != expected_parts_tax:
        raise EstimateStoreError(
            "Structured estimate generation failed. Tax totals did not reconcile."
        )
    if _money(totals.labor_hours) != _money(recalculated_labor_hours):
        raise EstimateStoreError(
            "Structured estimate generation failed. Labor hours did not reconcile."
        )

    estimated_total = _money(
        recalculated_labor_total
        + recalculated_parts_subtotal
        + expected_shop_supplies
        + expected_mobile_fee
        + expected_parts_tax
        + additional_fees
    )
    if _money(totals.estimated_total) != estimated_total:
        raise EstimateStoreError(
            "Structured estimate generation failed. Estimate total did not reconcile."
        )
    if estimated_total <= 0:
        raise EstimateStoreError(
            "Structured estimate generation failed. The estimate total must be greater than zero."
        )
    # `has_real_labor` is the single source of truth for whether the labor
    # section represents genuine priced work. An explicitly empty
    # `labor_items` list (a legitimate labor-optional job, e.g. a parts
    # drop-ship) is treated differently from a non-empty `labor_items` list
    # whose lines all collapsed to zero hours/total: the latter is a
    # fabricated placeholder line and must be rejected even when real parts
    # pricing is present, otherwise the customer would see a nonsense
    # free-labor line on an otherwise-priced estimate.
    has_real_labor = positive_labor_lines > 0
    if labor_items and not has_real_labor:
        raise EstimateStoreError(
            "Structured estimate generation failed. Customer-facing labor or parts data is required."
        )
    if not has_real_labor and recalculated_parts_subtotal <= 0:
        raise EstimateStoreError(
            "Structured estimate generation failed. Customer-facing labor or parts data is required."
        )


def _validate_estimate_ready_for_approval(
    *,
    estimate: Estimate,
    revision: EstimateRevision,
) -> None:
    if estimate.status not in {EstimateStatus.DRAFT.value, EstimateStatus.READY.value}:
        raise EstimateStoreError("Only draft or ready estimates can be sent for approval.")
    if not revision.terms_text.strip():
        raise EstimateStoreError("Customer-visible estimate terms are required before approval.")
    response_model = EstimateResponse.model_validate(revision.estimate_response_payload)
    _validate_generated_estimate(response_model)
    if _money(response_model.totals.estimated_total) <= 0:
        raise EstimateStoreError("Zero-value estimates cannot be sent for approval.")


def _estimate_query(auth: AuthContext) -> Select[tuple[Estimate]]:
    return select(Estimate).where(Estimate.owner_user_id == effective_owner_id(auth))


def _approval_request_query(token: str) -> Select[tuple[EstimateApprovalRequest]]:
    return select(EstimateApprovalRequest).where(
        EstimateApprovalRequest.token_hash == _hash_token(token)
    )


def _customer_summary(customer) -> EstimateCustomerSummary:  # type: ignore[no-untyped-def]
    return EstimateCustomerSummary(
        id=customer.id,
        display_name=customer_display_name(customer),
        email=customer.email,
        phone=customer.phone,
    )


def _vehicle_summary(vehicle) -> EstimateVehicleSummary:  # type: ignore[no-untyped-def]
    return EstimateVehicleSummary(
        id=vehicle.id,
        customer_id=vehicle.customer_id,
        display_name=vehicle_display_name(vehicle),
        vin=vehicle.vin,
        license_plate=vehicle.license_plate,
        current_mileage=vehicle.current_mileage,
    )


def _request_for_vehicle(payload: EstimateRecordBase, vehicle) -> EstimateRequest:  # type: ignore[no-untyped-def]
    return EstimateRequest(
        vehicle=VehicleInput(
            vin=vehicle.vin,
            year=vehicle.year,
            make=vehicle.make,
            model=vehicle.model,
            trim=vehicle.trim,
            engine=vehicle.engine,
            drivetrain=vehicle.drivetrain,
        ),
        job=payload.job,
        location=payload.location,
        labor_rate=payload.labor_rate,
        mobile_service_fee=payload.mobile_service_fee,
        shop_supplies_percent=payload.shop_supplies_percent,
        parts_tax_rate=payload.parts_tax_rate,
    )


def _resolve_payment_options(
    options: list[EstimatePaymentOption] | None,
) -> list[EstimatePaymentOption]:
    return options if options else _default_payment_options()


def _estimate_snapshot_payload(
    *,
    customer_summary: EstimateCustomerSummary,
    vehicle_summary: EstimateVehicleSummary,
    request_model: EstimateRequest,
    response_model: EstimateResponse,
    terms_text: str,
    payment_options: list[EstimatePaymentOption],
    approval_due_at: datetime | None,
) -> dict[str, object]:
    return {
        "customer": customer_summary.model_dump(mode="json"),
        "vehicle": vehicle_summary.model_dump(mode="json"),
        "request": request_model.model_dump(mode="json"),
        "estimate": response_model.model_dump(mode="json"),
        "terms_text": terms_text,
        "payment_options": [option.model_dump(mode="json") for option in payment_options],
        "approval_due_at": approval_due_at.isoformat() if approval_due_at else None,
    }


def _revision_to_read(revision: EstimateRevision) -> EstimateRevisionRead:
    customer = EstimateCustomerSummary.model_validate(revision.customer_snapshot)
    vehicle = EstimateVehicleSummary.model_validate(revision.vehicle_snapshot)
    request = EstimateRequest.model_validate(revision.estimate_request_payload)
    estimate = EstimateResponse.model_validate(revision.estimate_response_payload)
    payment_options = [
        EstimatePaymentOption.model_validate(item) for item in revision.payment_options_payload
    ]
    return EstimateRevisionRead(
        id=revision.id,
        revision_number=revision.revision_number,
        status=EstimateStatus(revision.status),
        customer=customer,
        vehicle=vehicle,
        request=request,
        estimate=estimate,
        terms_text=revision.terms_text,
        payment_options=payment_options,
        approval_due_at=ensure_utc(revision.approval_due_at) if revision.approval_due_at else None,
        content_hash=revision.content_hash,
        created_at=ensure_utc(revision.created_at),
    )


def _revision_to_approval_view(revision: EstimateRevision) -> EstimateApprovalRevisionView:
    """Build the narrow, customer-safe projection of a revision used by the
    public, token-authenticated approval-view endpoint. This intentionally
    omits the internal generation request (raw labor rate, mobile service
    fee, shop supplies percent, and parts tax rate overrides) and narrows the
    research payload to the customer-facing summary and warnings only,
    dropping unselected part-research options and internal labor reasoning
    (basis, special tools, risk flags)."""
    customer = EstimateCustomerSummary.model_validate(revision.customer_snapshot)
    vehicle = EstimateVehicleSummary.model_validate(revision.vehicle_snapshot)
    estimate = EstimateResponse.model_validate(revision.estimate_response_payload)
    payment_options = [
        EstimatePaymentOption.model_validate(item) for item in revision.payment_options_payload
    ]
    narrow_estimate = EstimateApprovalEstimateView(
        job=estimate.job,
        labor_items=estimate.labor_items,
        selected_parts=estimate.selected_parts,
        fee_items=estimate.fee_items,
        totals=estimate.totals,
        research=EstimateApprovalResearchView(
            summary=estimate.research.summary,
            warnings=estimate.research.warnings,
        ),
    )
    return EstimateApprovalRevisionView(
        id=revision.id,
        revision_number=revision.revision_number,
        status=EstimateStatus(revision.status),
        customer=customer,
        vehicle=vehicle,
        estimate=narrow_estimate,
        terms_text=revision.terms_text,
        payment_options=payment_options,
        approval_due_at=ensure_utc(revision.approval_due_at) if revision.approval_due_at else None,
        content_hash=revision.content_hash,
        created_at=ensure_utc(revision.created_at),
    )


def _event_to_read(event: EstimateApprovalEvent) -> EstimateApprovalEventRead:
    revision = event.revision.revision_number if event.revision else 0
    return EstimateApprovalEventRead(
        id=event.id,
        event_type=event.event_type,
        revision_number=revision,
        actor_type=event.actor_type,
        actor_name=event.actor_name,
        approval_method=event.approval_method,
        accepted_terms=event.accepted_terms,
        payment_option=event.payment_option,
        payment_plan_acknowledged=event.payment_plan_acknowledged,
        decline_reason=event.decline_reason,
        content_hash=event.content_hash,
        created_at=ensure_utc(event.created_at),
    )


def _estimate_to_read(estimate: Estimate) -> EstimateRead:
    revision = max(estimate.revisions, key=lambda item: item.revision_number)
    return EstimateRead(
        id=estimate.id,
        estimate_number=estimate.estimate_number,
        status=EstimateStatus(estimate.status),
        customer_id=estimate.customer_id,
        vehicle_id=estimate.vehicle_id,
        customer_display_name=customer_display_name(estimate.customer),
        vehicle_display_name=vehicle_display_name(estimate.vehicle),
        current_revision_number=estimate.current_revision_number,
        approved_revision_number=estimate.approved_revision_number,
        estimate_total=estimate.estimate_total,
        payment_option_selected=estimate.payment_option_selected,
        expires_at=ensure_utc(estimate.expires_at) if estimate.expires_at else None,
        is_archived=estimate.is_archived,
        created_at=ensure_utc(estimate.created_at),
        updated_at=ensure_utc(estimate.updated_at),
        current_revision=_revision_to_read(revision),
    )


def _require_estimate(db: Session, auth: AuthContext, estimate_id: int) -> Estimate:
    estimate = db.scalar(_estimate_query(auth).where(Estimate.id == estimate_id))
    if estimate is None:
        raise EstimateNotFoundError("Estimate not found.")
    return estimate


def _next_estimate_number(db: Session, auth: AuthContext) -> str:
    count = (
        db.scalar(
            select(func.count())
            .select_from(Estimate)
            .where(Estimate.owner_user_id == effective_owner_id(auth))
        )
        or 0
    )
    return f"EST-{effective_owner_id(auth):03d}-{count + 1:05d}"


async def _build_estimate_payload(
    *,
    auth: AuthContext,
    db: Session,
    payload: EstimateRecordBase,
    orchestrator: OptimusResearchOrchestrator,
) -> tuple[EstimateCustomerSummary, EstimateVehicleSummary, EstimateRequest, EstimateResponse]:
    customer = get_customer_model(db=db, auth=auth, customer_id=payload.customer_id)
    vehicle = get_vehicle_model(db=db, auth=auth, vehicle_id=payload.vehicle_id)
    if vehicle.customer_id != customer.id:
        raise EstimateStoreError("Vehicle does not belong to the selected customer.")
    request_model = _request_for_vehicle(payload, vehicle)
    response_model = await orchestrator.estimate_job(request_model)
    return (
        _customer_summary(customer),
        _vehicle_summary(vehicle),
        request_model,
        response_model,
    )


def _append_event(
    *,
    db: Session,
    estimate: Estimate,
    revision: EstimateRevision,
    event_type: str,
    actor_type: str,
    actor_name: str | None,
    approval_method: str | None,
    accepted_terms: bool | None,
    payment_option: str | None,
    payment_plan_acknowledged: bool | None,
    decline_reason: str | None,
    content_hash: str,
    approval_request_id: int | None = None,
    actor_user_id: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    approval_evidence: str | None = None,
) -> None:
    db.add(
        EstimateApprovalEvent(
            estimate_id=estimate.id,
            estimate_revision_id=revision.id,
            owner_user_id=estimate.owner_user_id,
            approval_request_id=approval_request_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            approval_method=approval_method,
            approval_evidence=approval_evidence,
            accepted_terms=accepted_terms,
            payment_option=payment_option,
            payment_plan_acknowledged=payment_plan_acknowledged,
            decline_reason=decline_reason,
            content_hash=content_hash,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )


async def create_estimate(
    *,
    db: Session,
    auth: AuthContext,
    payload: EstimateCreate,
    orchestrator: OptimusResearchOrchestrator,
) -> EstimateRead:
    (
        customer_summary,
        vehicle_summary,
        request_model,
        response_model,
    ) = await _build_estimate_payload(
        auth=auth,
        db=db,
        payload=payload,
        orchestrator=orchestrator,
    )
    _validate_generated_estimate(response_model)
    payment_options = _resolve_payment_options(payload.payment_options)
    approval_due_at = datetime.now(UTC) + timedelta(days=payload.expires_in_days)
    snapshot = _estimate_snapshot_payload(
        customer_summary=customer_summary,
        vehicle_summary=vehicle_summary,
        request_model=request_model,
        response_model=response_model,
        terms_text=payload.terms_text or DEFAULT_ESTIMATE_TERMS,
        payment_options=payment_options,
        approval_due_at=approval_due_at,
    )
    estimate = Estimate(
        owner_user_id=effective_owner_id(auth),
        customer_id=payload.customer_id,
        vehicle_id=payload.vehicle_id,
        estimate_number=_next_estimate_number(db, auth),
        status=EstimateStatus.DRAFT.value,
        current_revision_number=1,
        estimate_total=response_model.totals.estimated_total,
        expires_at=approval_due_at,
        is_archived=False,
    )
    db.add(estimate)
    db.flush()
    revision = EstimateRevision(
        estimate_id=estimate.id,
        owner_user_id=effective_owner_id(auth),
        revision_number=1,
        status=EstimateStatus.DRAFT.value,
        customer_snapshot=customer_summary.model_dump(mode="json"),
        vehicle_snapshot=vehicle_summary.model_dump(mode="json"),
        estimate_request_payload=request_model.model_dump(mode="json"),
        estimate_response_payload=response_model.model_dump(mode="json"),
        terms_text=payload.terms_text or DEFAULT_ESTIMATE_TERMS,
        payment_options_payload=[option.model_dump(mode="json") for option in payment_options],
        approval_due_at=approval_due_at,
        content_hash=_canonical_hash(snapshot),
    )
    db.add(revision)
    db.commit()
    db.refresh(estimate)
    return _estimate_to_read(estimate)


def get_estimate(*, db: Session, auth: AuthContext, estimate_id: int) -> EstimateRead:
    return _estimate_to_read(_require_estimate(db, auth, estimate_id))


def list_estimates(
    *,
    db: Session,
    auth: AuthContext,
    page: int,
    page_size: int,
    status: EstimateStatus | None,
    search: str | None,
    customer_id: int | None,
    vehicle_id: int | None,
    archived: bool,
) -> EstimateListResponse:
    if page < 1:
        raise EstimateStoreError("Page must be 1 or greater.")
    query = _estimate_query(auth).where(Estimate.is_archived == archived)
    if status is not None:
        query = query.where(Estimate.status == status.value)
    if customer_id is not None:
        get_customer_model(db=db, auth=auth, customer_id=customer_id)
        query = query.where(Estimate.customer_id == customer_id)
    if vehicle_id is not None:
        get_vehicle_model(db=db, auth=auth, vehicle_id=vehicle_id)
        query = query.where(Estimate.vehicle_id == vehicle_id)
    if search:
        token = search.strip().lower()
        if token:
            query = query.where(func.lower(Estimate.estimate_number).contains(token))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    estimates = db.scalars(
        query.order_by(Estimate.updated_at.desc(), Estimate.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return EstimateListResponse(
        items=[_estimate_to_read(item) for item in estimates],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(estimates) < total,
    )


def update_estimate(
    *,
    db: Session,
    auth: AuthContext,
    estimate_id: int,
    payload: EstimateUpdate,
) -> EstimateRead:
    estimate = _require_estimate(db, auth, estimate_id)
    if estimate.status in {EstimateStatus.APPROVED.value, EstimateStatus.AWAITING_APPROVAL.value}:
        raise EstimateStoreError("This estimate revision is locked. Create a new revision instead.")
    revision = max(estimate.revisions, key=lambda item: item.revision_number)
    if payload.terms_text is not None:
        revision.terms_text = payload.terms_text
    if payload.payment_options is not None:
        revision.payment_options_payload = [
            option.model_dump(mode="json")
            for option in _resolve_payment_options(payload.payment_options)
        ]
    if payload.expires_in_days is not None:
        revision.approval_due_at = datetime.now(UTC) + timedelta(days=payload.expires_in_days)
        estimate.expires_at = revision.approval_due_at
    if payload.status is not None:
        estimate.status = payload.status.value
        revision.status = payload.status.value
    content = _estimate_snapshot_payload(
        customer_summary=EstimateCustomerSummary.model_validate(revision.customer_snapshot),
        vehicle_summary=EstimateVehicleSummary.model_validate(revision.vehicle_snapshot),
        request_model=EstimateRequest.model_validate(revision.estimate_request_payload),
        response_model=EstimateResponse.model_validate(revision.estimate_response_payload),
        terms_text=revision.terms_text,
        payment_options=[
            EstimatePaymentOption.model_validate(item) for item in revision.payment_options_payload
        ],
        approval_due_at=revision.approval_due_at,
    )
    revision.content_hash = _canonical_hash(content)
    db.add(estimate)
    db.add(revision)
    db.commit()
    db.refresh(estimate)
    return _estimate_to_read(estimate)


async def create_estimate_revision(
    *,
    db: Session,
    auth: AuthContext,
    estimate_id: int,
    payload: EstimateRevisionCreate,
    orchestrator: OptimusResearchOrchestrator,
) -> EstimateRead:
    estimate = _require_estimate(db, auth, estimate_id)
    prior_revision = max(estimate.revisions, key=lambda item: item.revision_number)
    if estimate.status == EstimateStatus.APPROVED.value:
        estimate.status = EstimateStatus.SUPERSEDED.value
        prior_revision.status = EstimateStatus.SUPERSEDED.value
        _append_event(
            db=db,
            estimate=estimate,
            revision=prior_revision,
            event_type=EstimateStatus.SUPERSEDED.value,
            actor_type="internal",
            actor_name=auth.user.display_name,
            approval_method=EstimateApprovalMethod.INTERNAL.value,
            accepted_terms=None,
            payment_option=None,
            payment_plan_acknowledged=None,
            decline_reason=payload.reason,
            content_hash=prior_revision.content_hash,
            actor_user_id=auth.user.id,
        )
    (
        customer_summary,
        vehicle_summary,
        request_model,
        response_model,
    ) = await _build_estimate_payload(
        auth=auth,
        db=db,
        payload=payload,
        orchestrator=orchestrator,
    )
    _validate_generated_estimate(response_model)
    payment_options = _resolve_payment_options(payload.payment_options)
    approval_due_at = datetime.now(UTC) + timedelta(days=payload.expires_in_days)
    snapshot = _estimate_snapshot_payload(
        customer_summary=customer_summary,
        vehicle_summary=vehicle_summary,
        request_model=request_model,
        response_model=response_model,
        terms_text=payload.terms_text or DEFAULT_ESTIMATE_TERMS,
        payment_options=payment_options,
        approval_due_at=approval_due_at,
    )
    next_revision_number = estimate.current_revision_number + 1
    revision = EstimateRevision(
        estimate_id=estimate.id,
        owner_user_id=effective_owner_id(auth),
        revision_number=next_revision_number,
        status=EstimateStatus.READY.value,
        customer_snapshot=customer_summary.model_dump(mode="json"),
        vehicle_snapshot=vehicle_summary.model_dump(mode="json"),
        estimate_request_payload=request_model.model_dump(mode="json"),
        estimate_response_payload=response_model.model_dump(mode="json"),
        terms_text=payload.terms_text or DEFAULT_ESTIMATE_TERMS,
        payment_options_payload=[option.model_dump(mode="json") for option in payment_options],
        approval_due_at=approval_due_at,
        content_hash=_canonical_hash(snapshot),
    )
    estimate.customer_id = payload.customer_id
    estimate.vehicle_id = payload.vehicle_id
    estimate.current_revision_number = next_revision_number
    estimate.status = EstimateStatus.READY.value
    estimate.estimate_total = response_model.totals.estimated_total
    estimate.expires_at = approval_due_at
    db.add(estimate)
    db.add(revision)
    db.commit()
    db.refresh(estimate)
    return _estimate_to_read(estimate)


def send_estimate_for_approval(
    *,
    db: Session,
    auth: AuthContext,
    estimate_id: int,
    payload: EstimateSendForApprovalRequest,
    approval_base_url: str,
) -> EstimateApprovalSendResponse:
    estimate = _require_estimate(db, auth, estimate_id)
    revision = max(estimate.revisions, key=lambda item: item.revision_number)
    _validate_estimate_ready_for_approval(estimate=estimate, revision=revision)
    if revision.approval_due_at and ensure_utc(revision.approval_due_at) <= datetime.now(UTC):
        raise EstimateStoreError("Expired estimates must be extended or revised before approval.")
    token = secrets.token_urlsafe(32)
    approval_request = EstimateApprovalRequest(
        estimate_id=estimate.id,
        estimate_revision_id=revision.id,
        owner_user_id=effective_owner_id(auth),
        token_hash=_hash_token(token),
        status="active",
        expires_at=datetime.now(UTC) + timedelta(hours=payload.expires_in_hours),
        created_by_user_id=auth.user.id,
    )
    estimate.status = EstimateStatus.AWAITING_APPROVAL.value
    revision.status = EstimateStatus.AWAITING_APPROVAL.value
    estimate.expires_at = approval_request.expires_at
    db.add(estimate)
    db.add(revision)
    db.add(approval_request)
    db.flush()
    _append_event(
        db=db,
        estimate=estimate,
        revision=revision,
        event_type="sent",
        actor_type="internal",
        actor_name=auth.user.display_name,
        approval_method=payload.approval_method.value,
        accepted_terms=None,
        payment_option=None,
        payment_plan_acknowledged=None,
        decline_reason=None,
        content_hash=revision.content_hash,
        approval_request_id=approval_request.id,
        actor_user_id=auth.user.id,
    )
    record_notification(
        db=db,
        owner_user_id=estimate.owner_user_id,
        entity_type=NotificationEntityType.ESTIMATE,
        entity_id=estimate.id,
        event=NotificationEvent.ESTIMATE_SENT,
        title=f"Estimate {estimate.estimate_number} sent for approval",
        body=f"Revision {revision.revision_number} awaiting customer response.",
    )
    db.commit()
    return EstimateApprovalSendResponse(
        estimate_id=estimate.id,
        revision_number=revision.revision_number,
        status=EstimateStatus(estimate.status),
        expires_at=ensure_utc(approval_request.expires_at),
        approval_link=f"{approval_base_url}#token={token}",
    )


def _resolve_active_approval_request(db: Session, token: str) -> EstimateApprovalRequest:
    approval_request = db.scalar(_approval_request_query(token))
    if approval_request is None:
        raise EstimateApprovalTokenError("Approval token is invalid or unavailable.")
    if ensure_utc(approval_request.expires_at) <= datetime.now(UTC):
        approval_request.status = "expired"
        db.add(approval_request)
        db.commit()
        raise EstimateApprovalTokenError("Approval token is invalid or unavailable.")
    if approval_request.status != "active":
        raise EstimateApprovalTokenError("Approval token is invalid or unavailable.")
    return approval_request


def get_approval_view(
    *, db: Session, payload: EstimateApprovalTokenRequest
) -> EstimateApprovalPublicView:
    approval_request = _resolve_active_approval_request(db, payload.token)
    estimate = approval_request.estimate
    revision = approval_request.revision
    if revision.revision_number != estimate.current_revision_number:
        raise EstimateApprovalTokenError("Approval token is invalid or unavailable.")
    return EstimateApprovalPublicView(
        estimate_id=estimate.id,
        estimate_number=estimate.estimate_number,
        status=EstimateStatus(estimate.status),
        revision=_revision_to_approval_view(revision),
        token_expires_at=ensure_utc(approval_request.expires_at),
        token_status=approval_request.status,
        can_approve=True,
        can_decline=True,
    )


def approve_estimate(
    *,
    db: Session,
    payload: EstimateApprovalActionRequest,
    ip_address: str | None,
    user_agent: str | None,
) -> EstimateApprovalActionResponse:
    approval_request = _resolve_active_approval_request(db, payload.token)
    estimate = approval_request.estimate
    revision = approval_request.revision
    if revision.revision_number != payload.revision_number:
        raise EstimateStoreError("Estimate revision mismatch.")
    if revision.approval_due_at and ensure_utc(revision.approval_due_at) <= datetime.now(UTC):
        estimate.status = EstimateStatus.EXPIRED.value
        revision.status = EstimateStatus.EXPIRED.value
        approval_request.status = "expired"
        db.add(estimate)
        db.add(revision)
        db.add(approval_request)
        db.commit()
        raise EstimateStoreError("Expired estimates must be extended or revised before approval.")
    if not payload.accepted_terms:
        raise EstimateStoreError("Estimate terms must be accepted before approval.")
    payment_options = [
        EstimatePaymentOption.model_validate(item) for item in revision.payment_options_payload
    ]
    selected_option = next(
        (item for item in payment_options if item.code == payload.payment_option), None
    )
    if selected_option is None:
        raise EstimateStoreError("Selected payment option is not available for this estimate.")
    if (
        selected_option.requires_payment_plan_acknowledgement
        and not payload.payment_plan_acknowledged
    ):
        raise EstimateStoreError("Payment-plan acknowledgement is required for this option.")
    estimate.status = EstimateStatus.APPROVED.value
    revision.status = EstimateStatus.APPROVED.value
    estimate.approved_revision_number = revision.revision_number
    estimate.payment_option_selected = payload.payment_option.value
    approval_request.status = "used"
    approval_request.used_at = datetime.now(UTC)
    _append_event(
        db=db,
        estimate=estimate,
        revision=revision,
        event_type="approved",
        actor_type="customer",
        actor_name=payload.approving_name,
        approval_method=EstimateApprovalMethod.TYPED_SIGNATURE.value,
        accepted_terms=payload.accepted_terms,
        payment_option=payload.payment_option.value,
        payment_plan_acknowledged=payload.payment_plan_acknowledged,
        decline_reason=None,
        content_hash=revision.content_hash,
        approval_request_id=approval_request.id,
        ip_address=ip_address,
        user_agent=user_agent,
        approval_evidence=payload.typed_authorization,
    )
    db.add(estimate)
    db.add(revision)
    db.add(approval_request)
    # No AuthContext on this public token path -- the owner is derived from
    # the estimate row itself.
    record_notification(
        db=db,
        owner_user_id=estimate.owner_user_id,
        entity_type=NotificationEntityType.ESTIMATE,
        entity_id=estimate.id,
        event=NotificationEvent.ESTIMATE_APPROVED,
        title=f"Estimate {estimate.estimate_number} approved by {payload.approving_name}",
        body=f"Payment option: {payload.payment_option.value}.",
    )
    db.commit()
    used_at = approval_request.used_at
    if used_at is None:
        raise EstimateStoreError("Approval timestamp was not recorded.")
    return EstimateApprovalActionResponse(
        estimate_id=estimate.id,
        estimate_number=estimate.estimate_number,
        status=EstimateStatus(estimate.status),
        revision_number=revision.revision_number,
        decided_at=ensure_utc(used_at),
    )


def decline_estimate(
    *,
    db: Session,
    payload: EstimateDeclineActionRequest,
    ip_address: str | None,
    user_agent: str | None,
) -> EstimateApprovalActionResponse:
    approval_request = _resolve_active_approval_request(db, payload.token)
    estimate = approval_request.estimate
    revision = approval_request.revision
    if revision.revision_number != payload.revision_number:
        raise EstimateStoreError("Estimate revision mismatch.")
    estimate.status = EstimateStatus.DECLINED.value
    revision.status = EstimateStatus.DECLINED.value
    approval_request.status = "used"
    approval_request.used_at = datetime.now(UTC)
    _append_event(
        db=db,
        estimate=estimate,
        revision=revision,
        event_type="declined",
        actor_type="customer",
        actor_name=payload.declining_name,
        approval_method=EstimateApprovalMethod.LINK.value,
        accepted_terms=False,
        payment_option=None,
        payment_plan_acknowledged=None,
        decline_reason=payload.reason,
        content_hash=revision.content_hash,
        approval_request_id=approval_request.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(estimate)
    db.add(revision)
    db.add(approval_request)
    record_notification(
        db=db,
        owner_user_id=estimate.owner_user_id,
        entity_type=NotificationEntityType.ESTIMATE,
        entity_id=estimate.id,
        event=NotificationEvent.ESTIMATE_DECLINED,
        title=f"Estimate {estimate.estimate_number} declined by {payload.declining_name}",
        body=payload.reason,
    )
    db.commit()
    used_at = approval_request.used_at
    if used_at is None:
        raise EstimateStoreError("Decline timestamp was not recorded.")
    return EstimateApprovalActionResponse(
        estimate_id=estimate.id,
        estimate_number=estimate.estimate_number,
        status=EstimateStatus(estimate.status),
        revision_number=revision.revision_number,
        decided_at=ensure_utc(used_at),
    )


def approval_history(
    *, db: Session, auth: AuthContext, estimate_id: int
) -> EstimateApprovalAuditResponse:
    estimate = _require_estimate(db, auth, estimate_id)
    events = db.scalars(
        select(EstimateApprovalEvent)
        .where(EstimateApprovalEvent.estimate_id == estimate.id)
        .order_by(EstimateApprovalEvent.created_at.asc(), EstimateApprovalEvent.id.asc())
    ).all()
    return EstimateApprovalAuditResponse(
        estimate_id=estimate.id,
        estimate_number=estimate.estimate_number,
        status=EstimateStatus(estimate.status),
        events=[_event_to_read(event) for event in events],
    )
