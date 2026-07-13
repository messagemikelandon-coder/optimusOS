from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.main as main
from app.models import InvoiceIssueRequest, WorkOrderStatus, WorkOrderStatusUpdate
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_invoices_api import create_completed_work_order_with_invoice
from tests.test_work_orders_api import create_approved_estimate_for_auth


@pytest.mark.anyio
async def test_dashboard_summary_requires_authenticated_session(
    settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/dashboard/summary"), db_session, settings)
    assert excinfo.value.status_code == 401


@pytest.mark.anyio
async def test_dashboard_summary_empty_state_for_new_owner(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    summary = await main.get_dashboard_summary_record(db_session, auth, None, None)

    revenue = next(m for m in summary.metrics if m.key == "revenue")
    assert revenue.available is True
    assert revenue.value == 0.0

    average_repair_order = next(m for m in summary.metrics if m.key == "average_repair_order")
    assert average_repair_order.available is False
    assert average_repair_order.unavailable_reason is not None

    gross_profit = next(m for m in summary.metrics if m.key == "gross_profit")
    assert gross_profit.available is False
    assert "COGS" in (gross_profit.unavailable_reason or "")

    assert summary.current_operations.open_work_orders == 0
    assert summary.current_operations.awaiting_customer_approval == 0
    assert summary.financial_obligations.outstanding_balance == 0.0
    assert summary.revenue_breakdown == []
    assert summary.insights == []


@pytest.mark.anyio
async def test_dashboard_summary_reflects_real_issued_invoice(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await main.issue_invoice_record(
        invoice.id, InvoiceIssueRequest(due_in_days=30), db_session, settings, auth
    )

    date_from = datetime.now(UTC) - timedelta(days=1)
    date_to = datetime.now(UTC) + timedelta(days=1)
    summary = await main.get_dashboard_summary_record(db_session, auth, date_from, date_to)

    revenue = next(m for m in summary.metrics if m.key == "revenue")
    assert revenue.available is True
    assert revenue.value == pytest.approx(issued.invoice_total)

    labor_revenue = next(m for m in summary.metrics if m.key == "labor_revenue")
    assert labor_revenue.value == pytest.approx(issued.labor_total)

    parts_revenue = next(m for m in summary.metrics if m.key == "parts_revenue")
    assert parts_revenue.value == pytest.approx(issued.parts_total)

    average_repair_order = next(m for m in summary.metrics if m.key == "average_repair_order")
    assert average_repair_order.available is True
    assert average_repair_order.value == pytest.approx(issued.invoice_total)

    assert summary.current_operations.open_work_orders == 0  # work order completed, not open
    assert summary.financial_obligations.outstanding_balance == pytest.approx(issued.invoice_total)
    assert len(summary.revenue_trend) == 1
    assert summary.revenue_trend[0].values["revenue"] == pytest.approx(issued.invoice_total)

    labels = {item.label for item in summary.revenue_breakdown}
    assert labels == {"Labor", "Parts", "Fees"}


@pytest.mark.anyio
async def test_dashboard_summary_work_order_waiting_on_parts_counted(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    _, estimate = await create_approved_estimate_for_auth(monkeypatch, settings, db_session, auth)
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)
    await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.SCHEDULED, reason="Booked"),
        db_session,
        auth,
    )
    await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.IN_PROGRESS, reason="Started"),
        db_session,
        auth,
    )
    await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.WAITING_FOR_PARTS, reason="Backordered part"),
        db_session,
        auth,
    )

    summary = await main.get_dashboard_summary_record(db_session, auth, None, None)
    assert summary.current_operations.waiting_on_parts == 1
    assert summary.current_operations.open_work_orders == 1


@pytest.mark.anyio
async def test_dashboard_summary_invalid_date_range_rejected(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    now = datetime.now(UTC)
    with pytest.raises(HTTPException) as excinfo:
        await main.get_dashboard_summary_record(db_session, auth, now, now - timedelta(days=1))
    assert excinfo.value.status_code == 422


@pytest.mark.anyio
async def test_dashboard_summary_cross_user_isolation(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(db_session, username="dashboard-isolation-other", password="other-password-123")
    _, other_response = await login_as(
        settings, db_session, username="dashboard-isolation-other", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, owner_auth
    )
    await main.issue_invoice_record(
        invoice.id, InvoiceIssueRequest(due_in_days=30), db_session, settings, owner_auth
    )

    other_summary = await main.get_dashboard_summary_record(db_session, other_auth, None, None)
    revenue = next(m for m in other_summary.metrics if m.key == "revenue")
    assert revenue.value == 0.0
    assert other_summary.current_operations.open_work_orders == 0
    assert other_summary.financial_obligations.outstanding_balance == 0.0
