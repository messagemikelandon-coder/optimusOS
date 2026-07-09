from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

import app.main as main
import app.work_order_store as work_order_store
from app.auth import bootstrap_owner_account
from app.config import Settings
from app.db import Base, build_engine, build_session_factory
from app.db_models import Invoice
from app.models import (
    CustomerUpdate,
    EstimateFeeItem,
    InvoiceIssueRequest,
    InvoiceStatus,
    SelectedPart,
    VehicleUpdate,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
)
from app.orchestrator import OptimusResearchOrchestrator
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_estimate_approval_api import (
    fixture_estimate_response_with_sensitive_research,
    stub_sensitive_research_estimate_job,
)
from tests.test_work_orders_api import create_approved_estimate_for_auth


def extract_pdf_text(pdf_bytes: bytes) -> str:
    matches = re.findall(rb"\(((?:\\.|[^\\)])*)\)\s*Tj", pdf_bytes)
    parts: list[str] = []
    for raw in matches:
        text = raw.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\", b"\\")
        parts.append(text.decode("latin-1"))
    return "\n".join(parts)


async def stub_estimate_with_extra_fee(self, request):  # type: ignore[no-untyped-def]
    del self, request
    response = fixture_estimate_response_with_sensitive_research().model_copy(deep=True)
    response.fee_items.append(EstimateFeeItem(code="hazmat", label="Hazmat disposal", amount=8.3))
    response.totals.estimated_total += 8.3
    return response


async def stub_estimate_with_long_invoice_fields(self, request):  # type: ignore[no-untyped-def]
    del self, request
    response = fixture_estimate_response_with_sensitive_research().model_copy(deep=True)
    response.labor_items[0].description = "Labor line 1\nline 2 " + ("alignment " * 30)
    response.selected_parts[0] = SelectedPart.model_validate(
        {
            **response.selected_parts[0].model_dump(mode="json"),
            "part_name": "Part block\n" + ("ceramic-pad " * 28),
        }
    )
    return response


async def create_completed_work_order_with_invoice(
    monkeypatch,
    settings: Settings,
    db_session,
    auth,
    *,
    estimate_job_stub=stub_sensitive_research_estimate_job,
):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        OptimusResearchOrchestrator,
        "estimate_job",
        estimate_job_stub,
    )
    _, estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        auth,
        estimate_job_stub=estimate_job_stub,
    )
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)
    work_order = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.SCHEDULED, reason="Booked"),
        db_session,
        auth,
    )
    work_order = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.IN_PROGRESS, reason="Started"),
        db_session,
        auth,
    )
    work_order = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.COMPLETED, reason="Finished"),
        db_session,
        auth,
    )
    assert work_order.invoice_id is not None
    invoice = await main.get_invoice_record(work_order.invoice_id, db_session, auth)
    return work_order, invoice


@pytest.mark.anyio
async def test_completed_work_order_generates_draft_invoice(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    work_order, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )

    assert work_order.invoice_id == invoice.id
    assert invoice.status is InvoiceStatus.DRAFT
    assert invoice.invoice_number.startswith("INV-")
    assert invoice.work_order_id == work_order.id


@pytest.mark.anyio
async def test_duplicate_completion_does_not_duplicate_invoice(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    work_order, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    repeated = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.COMPLETED, reason="Repeated completion"),
        db_session,
        auth,
    )

    assert repeated.invoice_id == invoice.id
    assert db_session.scalar(select(func.count()).select_from(Invoice)) == 1


@pytest.mark.anyio
async def test_invoice_totals_and_line_items_preserve_customer_values(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )

    assert invoice.labor_total == 250
    assert invoice.parts_total == 120
    assert invoice.fees_total == 47.7
    assert invoice.invoice_total == 417.7
    assert [(item.kind.value, item.description) for item in invoice.line_items] == [
        ("labor", "Replace front brakes"),
        ("part", "Brake pad set"),
        ("fee", "Shop supplies"),
        ("fee", "Mobile service charge"),
        ("fee", "Parts tax"),
    ]


@pytest.mark.anyio
async def test_invoice_fee_total_includes_noncanonical_fee_items(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    monkeypatch.setattr(
        OptimusResearchOrchestrator,
        "estimate_job",
        stub_estimate_with_extra_fee,
    )

    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch,
        settings,
        db_session,
        auth,
        estimate_job_stub=stub_estimate_with_extra_fee,
    )

    assert invoice.fees_total == pytest.approx(56.0)
    assert invoice.invoice_total == pytest.approx(426.0)
    assert invoice.line_items[-1].description == "Hazmat disposal"


@pytest.mark.anyio
async def test_invoice_issue_sets_status_and_due_date(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await main.issue_invoice_record(
        invoice.id,
        InvoiceIssueRequest(due_in_days=15),
        db_session,
        settings,
        auth,
    )

    assert issued.status is InvoiceStatus.ISSUED
    assert issued.issued_at is not None
    assert issued.due_at is not None
    assert (issued.due_at - issued.issued_at).days == 15


@pytest.mark.anyio
async def test_invoice_html_and_pdf_exclude_internal_fields(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    html_response = await main.get_invoice_html(invoice.id, db_session, settings, auth)
    pdf_response = await main.get_invoice_pdf(invoice.id, db_session, settings, auth)
    html = bytes(html_response.body).decode("utf-8")
    pdf_text = extract_pdf_text(bytes(pdf_response.body))

    assert invoice.invoice_number in html
    assert '<link rel="stylesheet" href="/static/invoice.css">' in html
    assert "INTERNAL-LABOR-BASIS-MARKER-7788" not in html
    assert "INTERNAL-SPECIAL-TOOL-MARKER-7788" not in html
    assert "INTERNAL-RISK-FLAG-MARKER-7788" not in html
    assert "UNSELECTED-COMPETITOR-RETAILER-7788" not in html
    assert "INTERNAL-LABOR-BASIS-MARKER-7788" not in pdf_text
    assert "INTERNAL-SPECIAL-TOOL-MARKER-7788" not in pdf_text
    assert "INTERNAL-RISK-FLAG-MARKER-7788" not in pdf_text
    assert "UNSELECTED-COMPETITOR-RETAILER-7788" not in pdf_text


@pytest.mark.anyio
async def test_invoice_long_and_multiline_content_survives_generation(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    monkeypatch.setattr(
        OptimusResearchOrchestrator,
        "estimate_job",
        stub_estimate_with_long_invoice_fields,
    )

    work_order, invoice = await create_completed_work_order_with_invoice(
        monkeypatch,
        settings,
        db_session,
        auth,
        estimate_job_stub=stub_estimate_with_long_invoice_fields,
    )
    html_response = await main.get_invoice_html(invoice.id, db_session, settings, auth)
    pdf_response = await main.get_invoice_pdf(invoice.id, db_session, settings, auth)
    html = bytes(html_response.body).decode("utf-8")
    pdf_text = extract_pdf_text(bytes(pdf_response.body))

    assert work_order.invoice_id == invoice.id
    assert "Labor line 1\nline 2" in html
    assert "Part block\nceramic-pad" in html
    assert "Labor line 1\nline 2" in pdf_text
    assert "alignment alignment" in pdf_text
    assert "Part block\nceramic-pad" in pdf_text
    assert "ceramic-pad ceramic-pad" in pdf_text


@pytest.mark.anyio
async def test_invoice_cross_user_isolation(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, owner_auth
    )

    create_user(db_session, username="other-owner", password="other-password-123")
    _, other_response = await login_as(
        settings,
        db_session,
        username="other-owner",
        password="other-password-123",
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    with pytest.raises(HTTPException) as get_exc:
        await main.get_invoice_record(invoice.id, db_session, other_auth)
    assert get_exc.value.status_code == 404

    with pytest.raises(HTTPException) as html_exc:
        await main.get_invoice_html(invoice.id, db_session, settings, other_auth)
    assert html_exc.value.status_code == 404

    with pytest.raises(HTTPException) as pdf_exc:
        await main.get_invoice_pdf(invoice.id, db_session, settings, other_auth)
    assert pdf_exc.value.status_code == 404

    with pytest.raises(HTTPException) as issue_exc:
        await main.issue_invoice_record(
            invoice.id,
            InvoiceIssueRequest(due_in_days=15),
            db_session,
            settings,
            other_auth,
        )
    assert issue_exc.value.status_code == 404


@pytest.mark.anyio
async def test_invoice_snapshot_persists_after_customer_vehicle_updates(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    work_order, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    await main.update_customer_record(
        work_order.customer_id,
        CustomerUpdate(first_name="Jordan", last_name="Fleet"),
        db_session,
        auth,
    )
    await main.update_vehicle_record(
        work_order.vehicle_id,
        VehicleUpdate(color="Black", current_mileage=130000),
        db_session,
        auth,
    )

    fetched = await main.get_invoice_record(invoice.id, db_session, auth)
    assert fetched.customer.display_name == "Casey Jones"
    assert fetched.vehicle.display_name == "2018 Honda Civic EX"


@pytest.mark.anyio
async def test_invoice_persists_across_session_restart(
    monkeypatch, settings, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "invoices.sqlite"
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
        _, invoice = await create_completed_work_order_with_invoice(
            monkeypatch,
            file_settings,
            first_session,
            auth,
        )
        invoice_id = invoice.id
    finally:
        first_session.close()

    second_session = session_factory()
    try:
        _, response = await login_as(file_settings, second_session)
        auth = auth_context(file_settings, second_session, raw_cookie_from_response(response))
        fetched = await main.get_invoice_record(invoice_id, second_session, auth)
        assert fetched.id == invoice_id
        assert fetched.invoice_number
    finally:
        second_session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.mark.anyio
async def test_invoice_storage_failures_are_sanitized(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise SQLAlchemyError("db offline")

    monkeypatch.setattr(main, "get_invoice", boom)

    with pytest.raises(HTTPException) as excinfo:
        await main.get_invoice_record(1, db_session, auth)
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Invoice storage is unavailable."


@pytest.mark.anyio
async def test_completion_does_not_persist_without_invoice_creation(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    monkeypatch.setattr(
        OptimusResearchOrchestrator,
        "estimate_job",
        stub_sensitive_research_estimate_job,
    )
    _, estimate = await create_approved_estimate_for_auth(monkeypatch, settings, db_session, auth)
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)
    work_order = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.SCHEDULED, reason="Booked"),
        db_session,
        auth,
    )
    work_order = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.IN_PROGRESS, reason="Started"),
        db_session,
        auth,
    )

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise work_order_store.WorkOrderStoreError("invoice creation failed")

    monkeypatch.setattr(work_order_store, "ensure_draft_invoice_for_work_order", boom)

    with pytest.raises(HTTPException) as excinfo:
        await main.update_work_order_status_record(
            work_order.id,
            WorkOrderStatusUpdate(status=WorkOrderStatus.COMPLETED, reason="Finished"),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422

    reloaded = await main.get_work_order_record(work_order.id, db_session, auth)
    assert reloaded.status is WorkOrderStatus.IN_PROGRESS
    assert reloaded.invoice_id is None
