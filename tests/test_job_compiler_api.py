from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main as main
from app.db_models import Estimate, JobCompilation, Notification
from app.models import (
    CustomerCreate,
    DiagnosticConfidence,
    DiagnosticFindingCreate,
    DiagnosticFindingUpdate,
    DiagnosticSeverity,
    JobCompilationPartInput,
    JobCompilationRequest,
    JobCompilationServiceInput,
    JobCompilationStatus,
    PartCreate,
    PartUpdate,
    VehicleCreate,
    VehicleRead,
)
from tests.test_context_api import (
    auth_context,
    create_user,
    login_as,
    raw_cookie_from_response,
)

pytestmark = pytest.mark.anyio


async def _owner_auth(settings, db_session: Session):
    _, response = await login_as(settings, db_session)
    return auth_context(settings, db_session, raw_cookie_from_response(response))


async def _create_vehicle(db_session: Session, auth) -> VehicleRead:
    customer = await main.create_customer_record(
        CustomerCreate(first_name="Sample", last_name="Customer"), db_session, auth
    )
    return await main.create_vehicle_record(
        customer.id,
        VehicleCreate(year=2018, make="Honda", model="Civic"),
        db_session,
        auth,
    )


async def _create_finding(db_session: Session, auth, vehicle_id: int, *, conclusion="Worn pads."):
    finding = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(
            vehicle_id=vehicle_id,
            complaint="Grinding when braking.",
            symptoms="Metal-on-metal front axle under braking.",
            severity=DiagnosticSeverity.UNSAFE,
            confidence=DiagnosticConfidence.CONFIRMED,
            conclusion=conclusion,
        ),
        db_session,
        auth,
    )
    return finding


async def _create_part(
    db_session: Session,
    auth,
    *,
    unit_cost: float | None = 22.50,
    unit_price: float | None = 48.00,
    number: str = "BP-1",
):
    return await main.create_part_record(
        PartCreate(
            part_number=number,
            description="Front brake pad set",
            quantity_on_hand=8,
            unit_cost=unit_cost,
            unit_price=unit_price,
        ),
        db_session,
        auth,
    )


async def test_compile_produces_labor_parts_tasks_totals(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    part = await _create_part(db_session, auth)

    compiled = await main.compile_job_from_finding(
        finding.id,
        JobCompilationRequest(
            labor_rate=120.0,
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

    assert compiled.status == JobCompilationStatus.DRAFT
    assert compiled.revision_number == 1
    assert compiled.released is False
    # Labor reconciles deterministically: 1.5h * $120 = $180.
    assert len(compiled.labor_lines) == 1
    assert compiled.labor_lines[0].labor_total == 180.0
    # Parts priced from the customer unit_price ($48), never the cost ($22.50).
    assert len(compiled.part_lines) == 1
    assert compiled.part_lines[0].unit_price == 48.0
    assert compiled.part_lines[0].extended_price == 96.0
    # The customer-facing part-line projection carries no supplier cost field.
    assert "unit_cost" not in compiled.part_lines[0].model_dump()
    # Work-order task descriptor generated in sequence.
    assert compiled.tasks[0].sequence == 1
    assert compiled.tasks[0].title == "Replace front brake pads"
    # Totals reconcile: 180 labor + 96 parts, no fees.
    assert compiled.totals.labor_total == 180.0
    assert compiled.totals.parts_subtotal == 96.0
    assert compiled.totals.estimated_total == 276.0
    # Evidence snapshot preserved from the source finding.
    assert compiled.source_conclusion == "Worn pads."
    assert compiled.source_severity == DiagnosticSeverity.UNSAFE
    assert compiled.source_confidence == DiagnosticConfidence.CONFIRMED


async def test_compile_with_fees_reconciles(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    part = await _create_part(db_session, auth)

    compiled = await main.compile_job_from_finding(
        finding.id,
        JobCompilationRequest(
            labor_rate=120.0,
            shop_supplies_percent=5.0,
            parts_tax_rate=8.0,
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
    # shop_supplies = 180 * 5% = 9.00; parts_tax = 96 * 8% = 7.68.
    assert compiled.totals.shop_supplies == 9.0
    assert compiled.totals.parts_tax == 7.68
    assert compiled.totals.estimated_total == 292.68


async def test_recompile_identical_inputs_is_idempotent(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    part = await _create_part(db_session, auth)
    request = JobCompilationRequest(
        labor_rate=120.0,
        services=[
            JobCompilationServiceInput(
                title="Replace front brake pads",
                labor_hours=1.5,
                parts=[JobCompilationPartInput(part_id=part.id, quantity=2)],
            )
        ],
    )

    first = await main.compile_job_from_finding(finding.id, request, db_session, auth)
    second = await main.compile_job_from_finding(finding.id, request, db_session, auth)

    assert first.id == second.id
    assert second.revision_number == 1
    # No duplicate compilation rows were created.
    total = db_session.scalar(select(func.count()).select_from(JobCompilation))
    assert total == 1


async def test_recompile_changed_inputs_supersedes_and_revisions(
    settings, db_session: Session
) -> None:
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)

    first = await main.compile_job_from_finding(
        finding.id,
        JobCompilationRequest(
            labor_rate=120.0,
            services=[JobCompilationServiceInput(title="Brakes", labor_hours=1.5)],
        ),
        db_session,
        auth,
    )
    second = await main.compile_job_from_finding(
        finding.id,
        JobCompilationRequest(
            labor_rate=120.0,
            services=[JobCompilationServiceInput(title="Brakes", labor_hours=2.0)],
        ),
        db_session,
        auth,
    )

    assert second.id != first.id
    assert second.revision_number == 2
    assert second.status == JobCompilationStatus.DRAFT

    prior = await main.get_job_compilation_record(first.id, db_session, auth)
    assert prior.status == JobCompilationStatus.SUPERSEDED
    assert prior.superseded_by_id == second.id

    # Exactly one active draft remains for the finding.
    drafts = await main.list_job_compilation_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=50,
        compilation_status=JobCompilationStatus.DRAFT,
    )
    assert drafts.total == 1
    assert drafts.items[0].id == second.id

    events = await main.list_job_compilation_event_records(second.id, db_session, auth)
    assert {event.event_type for event in events.events} == {"recompiled"}
    prior_events = await main.list_job_compilation_event_records(first.id, db_session, auth)
    assert {event.event_type for event in prior_events.events} == {"compiled", "superseded"}


async def test_compile_rejects_finding_without_conclusion(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Noise only."),
        db_session,
        auth,
    )
    with pytest.raises(HTTPException) as excinfo:
        await main.compile_job_from_finding(
            finding.id,
            JobCompilationRequest(
                labor_rate=120.0,
                services=[JobCompilationServiceInput(title="X", labor_hours=1.0)],
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422


async def test_compile_rejects_archived_finding(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    await main.archive_diagnostic_finding_record(finding.id, db_session, auth)
    with pytest.raises(HTTPException) as excinfo:
        await main.compile_job_from_finding(
            finding.id,
            JobCompilationRequest(
                labor_rate=120.0,
                services=[JobCompilationServiceInput(title="X", labor_hours=1.0)],
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422


async def test_compile_rejects_part_without_customer_price(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    part = await _create_part(db_session, auth, unit_price=None)
    with pytest.raises(HTTPException) as excinfo:
        await main.compile_job_from_finding(
            finding.id,
            JobCompilationRequest(
                labor_rate=120.0,
                services=[
                    JobCompilationServiceInput(
                        title="X",
                        labor_hours=1.0,
                        parts=[JobCompilationPartInput(part_id=part.id, quantity=1)],
                    )
                ],
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422


async def test_compile_rejects_cross_shop_part(settings, db_session: Session) -> None:
    owner_a = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, owner_a)
    finding = await _create_finding(db_session, owner_a, vehicle.id)

    other = create_user(
        db_session, username="owner-b", password="owner-b-pass-123", settings=settings
    )
    _, response_b = await login_as(
        settings, db_session, username="owner-b", password="owner-b-pass-123"
    )
    owner_b = auth_context(settings, db_session, raw_cookie_from_response(response_b))
    part_b = await _create_part(db_session, owner_b, number="B-1")
    assert other.id != owner_a.user.id

    with pytest.raises(HTTPException) as excinfo:
        await main.compile_job_from_finding(
            finding.id,
            JobCompilationRequest(
                labor_rate=120.0,
                services=[
                    JobCompilationServiceInput(
                        title="X",
                        labor_hours=1.0,
                        parts=[JobCompilationPartInput(part_id=part_b.id, quantity=1)],
                    )
                ],
            ),
            db_session,
            owner_a,
        )
    assert excinfo.value.status_code == 422


async def test_cross_shop_finding_is_not_found(settings, db_session: Session) -> None:
    owner_a = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, owner_a)
    finding = await _create_finding(db_session, owner_a, vehicle.id)

    create_user(db_session, username="owner-c", password="owner-c-pass-123", settings=settings)
    _, response_c = await login_as(
        settings, db_session, username="owner-c", password="owner-c-pass-123"
    )
    owner_c = auth_context(settings, db_session, raw_cookie_from_response(response_c))

    with pytest.raises(HTTPException) as excinfo:
        await main.compile_job_from_finding(
            finding.id,
            JobCompilationRequest(
                labor_rate=120.0,
                services=[JobCompilationServiceInput(title="X", labor_hours=1.0)],
            ),
            db_session,
            owner_c,
        )
    assert excinfo.value.status_code == 404


async def test_aggregates_duplicate_part_across_services(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    part = await _create_part(db_session, auth)

    compiled = await main.compile_job_from_finding(
        finding.id,
        JobCompilationRequest(
            labor_rate=100.0,
            services=[
                JobCompilationServiceInput(
                    title="Service A",
                    labor_hours=1.0,
                    parts=[JobCompilationPartInput(part_id=part.id, quantity=1)],
                ),
                JobCompilationServiceInput(
                    title="Service B",
                    labor_hours=1.0,
                    parts=[JobCompilationPartInput(part_id=part.id, quantity=1)],
                ),
            ],
        ),
        db_session,
        auth,
    )
    assert len(compiled.part_lines) == 1
    assert compiled.part_lines[0].quantity == 2
    assert compiled.part_lines[0].extended_price == 96.0


async def test_compile_creates_no_estimate_or_notification(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    part = await _create_part(db_session, auth)

    estimates_before = db_session.scalar(select(func.count()).select_from(Estimate))
    notifications_before = db_session.scalar(select(func.count()).select_from(Notification))

    await main.compile_job_from_finding(
        finding.id,
        JobCompilationRequest(
            labor_rate=120.0,
            services=[
                JobCompilationServiceInput(
                    title="Brakes",
                    labor_hours=1.5,
                    parts=[JobCompilationPartInput(part_id=part.id, quantity=2)],
                )
            ],
        ),
        db_session,
        auth,
    )

    # The deterministic compiler never creates an estimate, sends anything, or
    # notifies -- customer release is a separate, explicitly gated step.
    assert db_session.scalar(select(func.count()).select_from(Estimate)) == estimates_before
    assert db_session.scalar(select(func.count()).select_from(Notification)) == notifications_before


async def test_changed_part_price_forces_new_revision(settings, db_session: Session) -> None:
    # Idempotency must key on the computed output (which includes the catalog
    # customer price), not just the raw request inputs: correcting a part's
    # price and recompiling the same finding + services must NOT silently
    # return the stale draft with old totals.
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    part = await _create_part(db_session, auth, unit_price=48.00)
    request = JobCompilationRequest(
        labor_rate=120.0,
        services=[
            JobCompilationServiceInput(
                title="Brakes",
                labor_hours=1.0,
                parts=[JobCompilationPartInput(part_id=part.id, quantity=1)],
            )
        ],
    )
    first = await main.compile_job_from_finding(finding.id, request, db_session, auth)
    assert first.part_lines[0].unit_price == 48.0

    # Correct the customer price in the catalog, then recompile identical inputs.
    await main.update_part_record(part.id, PartUpdate(unit_price=60.00), db_session, auth)
    second = await main.compile_job_from_finding(finding.id, request, db_session, auth)

    assert second.id != first.id
    assert second.revision_number == 2
    assert second.part_lines[0].unit_price == 60.0
    assert second.totals.parts_subtotal == 60.0


async def test_changed_diagnosis_forces_new_revision(settings, db_session: Session) -> None:
    auth = await _owner_auth(settings, db_session)
    vehicle = await _create_vehicle(db_session, auth)
    finding = await _create_finding(db_session, auth, vehicle.id)
    request = JobCompilationRequest(
        labor_rate=120.0,
        services=[JobCompilationServiceInput(title="Brakes", labor_hours=1.5)],
    )
    first = await main.compile_job_from_finding(finding.id, request, db_session, auth)

    # Editing the underlying diagnosis changes the compile inputs' provenance.
    await main.update_diagnostic_finding_record(
        finding.id,
        DiagnosticFindingUpdate(conclusion="Rotors also scored."),
        db_session,
        auth,
    )
    second = await main.compile_job_from_finding(finding.id, request, db_session, auth)
    assert second.id != first.id
    assert second.revision_number == 2
    assert second.source_conclusion == "Rotors also scored."
