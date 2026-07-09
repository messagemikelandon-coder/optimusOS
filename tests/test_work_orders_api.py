from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

import app.main as main
from app.auth import bootstrap_owner_account
from app.config import Settings
from app.db import Base, build_engine, build_session_factory
from app.db_models import Estimate, WorkOrder
from app.models import (
    EstimatePaymentOptionCode,
    EstimateStatus,
    WorkOrderNoteCreate,
    WorkOrderNoteVisibility,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
    WorkOrderUpdate,
)
from app.orchestrator import OptimusResearchOrchestrator
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_estimate_approval_api import create_estimate_for_auth, stub_estimate_job


async def create_approved_estimate_for_auth(
    monkeypatch,
    settings: Settings,
    db_session,
    auth,
    *,
    payment_option: EstimatePaymentOptionCode = EstimatePaymentOptionCode.PAY_IN_FULL,
    estimate_job_stub=stub_estimate_job,
    **vehicle_overrides,
):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", estimate_job_stub)
    _, vehicle, estimate = await create_estimate_for_auth(
        settings,
        db_session,
        auth,
        **vehicle_overrides,
    )
    estimate_model = db_session.get(Estimate, estimate.id)
    assert estimate_model is not None
    estimate_model.status = EstimateStatus.APPROVED.value
    estimate_model.approved_revision_number = estimate_model.current_revision_number
    estimate_model.payment_option_selected = payment_option.value
    db_session.add(estimate_model)
    db_session.commit()
    db_session.refresh(estimate_model)
    return vehicle, estimate_model


@pytest.mark.anyio
async def test_work_order_routes_require_authenticated_session(settings, db_session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/work-orders"), db_session, settings)
    assert excinfo.value.status_code == 401


@pytest.mark.anyio
async def test_approved_estimate_converts_to_work_order(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle, estimate = await create_approved_estimate_for_auth(
        monkeypatch, settings, db_session, auth
    )

    created = await main.create_work_order_record(estimate.id, db_session, auth)

    assert created.estimate_id == estimate.id
    assert created.estimate_revision_id == estimate.revisions[0].id
    assert created.status is WorkOrderStatus.READY_TO_SCHEDULE
    assert created.customer_id == estimate.customer_id
    assert created.vehicle_id == vehicle.id
    assert created.estimate_number == estimate.estimate_number


@pytest.mark.anyio
@pytest.mark.parametrize(
    "estimate_status",
    [EstimateStatus.DRAFT, EstimateStatus.DECLINED, EstimateStatus.AWAITING_APPROVAL],
)
async def test_non_approved_estimate_rejected_for_conversion(  # type: ignore[no-untyped-def]
    monkeypatch,
    settings,
    db_session,
    estimate_status: EstimateStatus,
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, _, estimate = await create_estimate_for_auth(settings, db_session, auth)
    estimate_model = db_session.get(Estimate, estimate.id)
    assert estimate_model is not None
    estimate_model.status = estimate_status.value
    estimate_model.approved_revision_number = None
    db_session.add(estimate_model)
    db_session.commit()

    with pytest.raises(HTTPException) as excinfo:
        await main.create_work_order_record(estimate.id, db_session, auth)
    assert excinfo.value.status_code == 422


@pytest.mark.anyio
async def test_duplicate_work_order_conversion_is_idempotent(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, estimate = await create_approved_estimate_for_auth(monkeypatch, settings, db_session, auth)

    first = await main.create_work_order_record(estimate.id, db_session, auth)
    second = await main.create_work_order_record(estimate.id, db_session, auth)

    assert first.id == second.id
    assert db_session.scalar(select(func.count()).select_from(WorkOrder)) == 1


@pytest.mark.anyio
async def test_work_order_preserves_approved_revision_snapshot(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, estimate = await create_approved_estimate_for_auth(monkeypatch, settings, db_session, auth)

    created = await main.create_work_order_record(estimate.id, db_session, auth)

    assert created.source_revision.revision_number == estimate.approved_revision_number
    assert created.title == created.source_revision.request.job
    assert created.complaint == created.source_revision.request.job
    assert created.source_revision.estimate.selected_parts[0].part_name == "Brake pad set"


@pytest.mark.anyio
async def test_work_order_copies_labor_parts_and_totals(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, estimate = await create_approved_estimate_for_auth(monkeypatch, settings, db_session, auth)

    created = await main.create_work_order_record(estimate.id, db_session, auth)

    assert created.estimate_total == 417.7
    assert created.labor_hours_estimate == 2.5
    assert created.source_revision.estimate.totals.estimated_total == 417.7
    assert created.source_revision.estimate.labor_items[0].labor_total == 250
    assert created.source_revision.estimate.selected_parts[0].extended_price == 120


@pytest.mark.anyio
async def test_work_order_cross_user_isolation(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    _, estimate = await create_approved_estimate_for_auth(
        monkeypatch, settings, db_session, owner_auth
    )
    created = await main.create_work_order_record(estimate.id, db_session, owner_auth)

    create_user(db_session, username="other-owner", password="other-password-123")
    _, other_response = await login_as(
        settings,
        db_session,
        username="other-owner",
        password="other-password-123",
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    with pytest.raises(HTTPException) as get_exc:
        await main.get_work_order_record(created.id, db_session, other_auth)
    assert get_exc.value.status_code == 404

    with pytest.raises(HTTPException) as create_exc:
        await main.create_work_order_record(estimate.id, db_session, other_auth)
    assert create_exc.value.status_code == 404


@pytest.mark.anyio
async def test_valid_work_order_status_transitions(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, estimate = await create_approved_estimate_for_auth(monkeypatch, settings, db_session, auth)
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)

    scheduled = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.SCHEDULED, reason="Booked"),
        db_session,
        auth,
    )
    in_progress = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.IN_PROGRESS, reason="Started"),
        db_session,
        auth,
    )
    waiting = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.WAITING_FOR_PARTS, reason="Need rotor"),
        db_session,
        auth,
    )
    resumed = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.IN_PROGRESS, reason="Parts arrived"),
        db_session,
        auth,
    )
    completed = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.COMPLETED, reason="Done"),
        db_session,
        auth,
    )

    assert scheduled.status is WorkOrderStatus.SCHEDULED
    assert in_progress.status is WorkOrderStatus.IN_PROGRESS
    assert waiting.status is WorkOrderStatus.WAITING_FOR_PARTS
    assert resumed.status is WorkOrderStatus.IN_PROGRESS
    assert completed.status is WorkOrderStatus.COMPLETED
    assert [event.to_status for event in completed.status_history] == [
        WorkOrderStatus.READY_TO_SCHEDULE,
        WorkOrderStatus.SCHEDULED,
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.WAITING_FOR_PARTS,
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.COMPLETED,
    ]


@pytest.mark.anyio
async def test_invalid_work_order_status_transition_rejected(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, estimate = await create_approved_estimate_for_auth(monkeypatch, settings, db_session, auth)
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.update_work_order_status_record(
            work_order.id,
            WorkOrderStatusUpdate(status=WorkOrderStatus.COMPLETED),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 409


@pytest.mark.anyio
async def test_payment_plan_prerequisites_block_ready_transition(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        auth,
        payment_option=EstimatePaymentOptionCode.TWO_MONTH_PLAN,
    )
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)

    assert work_order.status is WorkOrderStatus.PENDING_REQUIREMENTS
    assert WorkOrderStatus.READY_TO_SCHEDULE.value in work_order.blocked_transitions
    assert WorkOrderStatus.READY_TO_SCHEDULE not in work_order.allowed_next_statuses

    with pytest.raises(HTTPException) as excinfo:
        await main.update_work_order_status_record(
            work_order.id,
            WorkOrderStatusUpdate(status=WorkOrderStatus.READY_TO_SCHEDULE),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422

    updated = await main.update_work_order_record(
        work_order.id,
        WorkOrderUpdate(deposit_received=True, authorization_confirmed=True),
        db_session,
        auth,
    )
    ready = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.READY_TO_SCHEDULE),
        db_session,
        auth,
    )
    assert updated.deposit_received is True
    assert updated.authorization_confirmed is True
    assert ready.status is WorkOrderStatus.READY_TO_SCHEDULE


@pytest.mark.anyio
async def test_work_order_notes_preserve_visibility_separation(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, estimate = await create_approved_estimate_for_auth(monkeypatch, settings, db_session, auth)
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)

    await main.add_work_order_note_record(
        work_order.id,
        WorkOrderNoteCreate(note="Internal checklist", visibility=WorkOrderNoteVisibility.INTERNAL),
        db_session,
        auth,
    )
    detailed = await main.add_work_order_note_record(
        work_order.id,
        WorkOrderNoteCreate(
            note="Customer waiting on ETA", visibility=WorkOrderNoteVisibility.CUSTOMER
        ),
        db_session,
        auth,
    )

    assert [(note.visibility, note.note) for note in detailed.notes] == [
        (WorkOrderNoteVisibility.INTERNAL, "Internal checklist"),
        (WorkOrderNoteVisibility.CUSTOMER, "Customer waiting on ETA"),
    ]


@pytest.mark.anyio
async def test_work_order_note_updates_list_recency(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, first_estimate = await create_approved_estimate_for_auth(
        monkeypatch, settings, db_session, auth
    )
    _, second_estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        auth,
        vin="1HGCM82633A004353",
        license_plate="8ABC124",
        fleet_unit_number="Unit 8",
    )

    first_work_order = await main.create_work_order_record(first_estimate.id, db_session, auth)
    second_work_order = await main.create_work_order_record(second_estimate.id, db_session, auth)

    listed_before = await main.list_work_order_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        status_filter=None,
        search=None,
        customer_id=None,
        vehicle_id=None,
    )
    assert [item.id for item in listed_before.items][:2] == [
        second_work_order.id,
        first_work_order.id,
    ]

    await main.add_work_order_note_record(
        first_work_order.id,
        WorkOrderNoteCreate(
            note="Fresh note should move this work order to the top.",
            visibility=WorkOrderNoteVisibility.INTERNAL,
        ),
        db_session,
        auth,
    )

    listed_after = await main.list_work_order_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        status_filter=None,
        search=None,
        customer_id=None,
        vehicle_id=None,
    )
    assert [item.id for item in listed_after.items][:2] == [
        first_work_order.id,
        second_work_order.id,
    ]


@pytest.mark.anyio
async def test_work_order_can_be_cancelled(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, estimate = await create_approved_estimate_for_auth(monkeypatch, settings, db_session, auth)
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)

    cancelled = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.CANCELLED, reason="Customer postponed"),
        db_session,
        auth,
    )
    assert cancelled.status is WorkOrderStatus.CANCELLED
    assert cancelled.status_history[-1].to_status is WorkOrderStatus.CANCELLED


@pytest.mark.anyio
async def test_work_order_persists_across_session_restart(
    monkeypatch, settings, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "work-orders.sqlite"
    file_settings = settings.model_copy(update={"database_url": f"sqlite+pysqlite:///{db_path}"})
    engine = build_engine(file_settings.database_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(file_settings.database_url)

    first_session = session_factory()
    try:
        bootstrap_owner_account(settings=file_settings, db=first_session)
        _, response = await login_as(file_settings, first_session)
        auth = auth_context(file_settings, first_session, raw_cookie_from_response(response))
        _, estimate = await create_approved_estimate_for_auth(
            monkeypatch,
            file_settings,
            first_session,
            auth,
        )
        created = await main.create_work_order_record(estimate.id, first_session, auth)
        created_id = created.id
    finally:
        first_session.close()

    second_session = session_factory()
    try:
        _, response = await login_as(file_settings, second_session)
        auth = auth_context(file_settings, second_session, raw_cookie_from_response(response))
        fetched = await main.get_work_order_record(created_id, second_session, auth)
        assert fetched.id == created_id
        assert fetched.estimate_number
    finally:
        second_session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.mark.anyio
async def test_work_order_storage_failures_are_sanitized(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise SQLAlchemyError("db offline")

    monkeypatch.setattr(main, "create_work_order_from_estimate", boom)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_work_order_record(1, db_session, auth)
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Work-order storage is unavailable."
