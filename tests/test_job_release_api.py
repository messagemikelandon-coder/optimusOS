from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main as main
from app.db_models import Estimate, JobCompilation
from app.models import (
    CustomerCreate,
    EstimateSendForApprovalRequest,
    EstimateStatus,
    JobCompilationPartInput,
    JobCompilationRequest,
    JobCompilationServiceInput,
    VehicleCreate,
)
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_job_compiler_api import _create_finding, _create_part, _create_vehicle, _owner_auth

pytestmark = pytest.mark.anyio


async def _compile_job(
    db_session: Session, auth, *, unit_price=48.00, unit_cost=22.50, labor_rate=120.0
):
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    part = await _create_part(db_session, auth, unit_price=unit_price, unit_cost=unit_cost)
    compiled = await main.compile_job_from_finding(
        finding.id,
        JobCompilationRequest(
            labor_rate=labor_rate,
            services=[
                JobCompilationServiceInput(
                    title="Replace front brake pads",
                    labor_hours=1.5,
                    parts=[JobCompilationPartInput(part_id=part.id, quantity=2)],
                )
            ],
        ),
        db_session,
        auth,
    )
    return compiled, vehicle, finding, part


async def test_release_creates_draft_estimate(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    compiled, vehicle, _, _ = await _compile_job(db_session, auth)

    result = await main.release_job_compilation_record(compiled.id, db_session, auth)

    assert result.already_released is False
    assert result.estimate.status is EstimateStatus.DRAFT
    # The estimate is a real canonical estimate carrying the compiled totals.
    assert result.estimate.estimate_total is not None
    assert float(result.estimate.estimate_total) == compiled.totals.estimated_total
    assert result.estimate.vehicle_id == vehicle.id
    # Labor + customer-priced parts reconcile into the estimate revision.
    est = result.estimate.current_revision.estimate
    assert est.labor_items[0].labor_total == 180.0
    assert est.selected_parts[0].unit_price == 48.0
    assert est.selected_parts[0].extended_price == 96.0
    assert est.selected_parts[0].url is None  # in-house catalog: no retailer URL
    # No supplier cost is anywhere in the released estimate.
    assert "unit_cost" not in est.selected_parts[0].model_dump()
    # The compilation now links to the estimate and is marked released.
    assert result.compilation.released_estimate_id == result.estimate.id
    stored = db_session.get(JobCompilation, compiled.id)
    assert stored is not None and stored.released is True


async def test_release_is_idempotent(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    compiled, _, _, _ = await _compile_job(db_session, auth)

    first = await main.release_job_compilation_record(compiled.id, db_session, auth)
    second = await main.release_job_compilation_record(compiled.id, db_session, auth)

    assert second.already_released is True
    assert second.estimate.id == first.estimate.id
    # Exactly one estimate was created.
    assert db_session.scalar(select(func.count()).select_from(Estimate)) == 1
    # Exactly one 'released' event exists.
    events = await main.list_job_compilation_event_records(compiled.id, db_session, auth)
    assert [e.event_type for e in events.events].count("released") == 1


async def test_release_rejects_superseded_compilation(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    compiled, _, finding, part = await _compile_job(db_session, auth)
    # Recompile with changed inputs -> supersedes the first compilation.
    await main.compile_job_from_finding(
        finding.id,
        JobCompilationRequest(
            labor_rate=120.0,
            services=[
                JobCompilationServiceInput(
                    title="Replace front brake pads",
                    labor_hours=2.0,
                    parts=[JobCompilationPartInput(part_id=part.id, quantity=2)],
                )
            ],
        ),
        db_session,
        auth,
    )
    with pytest.raises(HTTPException) as excinfo:
        await main.release_job_compilation_record(compiled.id, db_session, auth)
    assert excinfo.value.status_code == 422


async def test_release_rejects_cross_shop_compilation(settings, db_session: Session) -> None:
    owner_a = await _owner_auth(settings, db_session)
    compiled, _, _, _ = await _compile_job(db_session, owner_a)

    create_user(db_session, username="owner-b", password="owner-b-pass-123", settings=settings)
    _, resp_b = await login_as(
        settings, db_session, username="owner-b", password="owner-b-pass-123"
    )
    owner_b = auth_context(settings, db_session, raw_cookie_from_response(resp_b))

    with pytest.raises(HTTPException) as excinfo:
        await main.release_job_compilation_record(compiled.id, db_session, owner_b)
    assert excinfo.value.status_code == 404
    # No estimate leaked into owner B's shop.
    assert db_session.scalar(select(func.count()).select_from(Estimate)) == 0


async def test_release_preserves_severity_and_confidence(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    compiled, _, _, _ = await _compile_job(db_session, auth)
    result = await main.release_job_compilation_record(compiled.id, db_session, auth)
    research = result.estimate.current_revision.estimate.research
    # The source finding is unsafe + confirmed (from _create_finding).
    assert research.labor.confidence.value == "high"
    assert any("Safety-critical" in warning for warning in research.warnings)


async def test_released_estimate_flows_through_approval_pipeline(
    settings, db_session: Session
) -> None:
    # Proves the released estimate is a real canonical estimate: it can be sent
    # for customer approval through the existing pipeline (no parallel record).
    auth = await _owner_auth(settings, db_session)
    compiled, _, _, _ = await _compile_job(db_session, auth)
    result = await main.release_job_compilation_record(compiled.id, db_session, auth)

    # Released estimates start as DRAFT -- release never auto-sends/auto-approves.
    assert result.estimate.status is EstimateStatus.DRAFT

    sent = await main.send_estimate_record_for_approval(
        result.estimate.id,
        EstimateSendForApprovalRequest(),
        db_session,
        auth,
        request_for("/api/estimates/1/send-for-approval", method="POST"),
    )
    assert sent.status is EstimateStatus.AWAITING_APPROVAL


async def test_release_rejects_compilation_from_another_shop_not_found(
    settings, db_session: Session
) -> None:
    auth = await _owner_auth(settings, db_session)
    with pytest.raises(HTTPException) as excinfo:
        await main.release_job_compilation_record(999999, db_session, auth)
    assert excinfo.value.status_code == 404


async def test_release_vehicle_without_year_or_vin(settings, db_session: Session) -> None:
    # A canonical vehicle with only make+model (no year, no VIN) is valid in the
    # system; releasing a compilation for it must not fail building the estimate
    # request (the request's vehicle is optional; the response's DecodedVehicle
    # + estimate.vehicle_id carry identity).
    auth = await _owner_auth(settings, db_session)
    customer = await main.create_customer_record(
        CustomerCreate(first_name="No", last_name="Year"), db_session, auth
    )
    vehicle = await main.create_vehicle_record(
        customer.id, VehicleCreate(make="Honda", model="Civic"), db_session, auth
    )
    finding = await _create_finding(db_session, auth, vehicle.id)
    compiled = await main.compile_job_from_finding(
        finding.id,
        JobCompilationRequest(
            labor_rate=100.0,
            services=[JobCompilationServiceInput(title="Diagnose", labor_hours=1.0)],
        ),
        db_session,
        auth,
    )
    result = await main.release_job_compilation_record(compiled.id, db_session, auth)
    assert result.estimate.status is EstimateStatus.DRAFT
    assert result.estimate.vehicle_id == vehicle.id


async def test_release_labor_only_compilation(settings, db_session: Session) -> None:
    # A labor-only job (no parts) reconciles and releases: selected_parts is
    # empty, and the estimate total equals the labor total.
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    compiled = await main.compile_job_from_finding(
        finding.id,
        JobCompilationRequest(
            labor_rate=100.0,
            services=[JobCompilationServiceInput(title="Diagnose", labor_hours=2.0)],
        ),
        db_session,
        auth,
    )
    result = await main.release_job_compilation_record(compiled.id, db_session, auth)
    est = result.estimate.current_revision.estimate
    assert est.selected_parts == []
    assert est.labor_items[0].labor_total == 200.0
    assert result.estimate.estimate_total is not None
    assert float(result.estimate.estimate_total) == 200.0
