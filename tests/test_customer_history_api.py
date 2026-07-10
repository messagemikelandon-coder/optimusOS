from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.main as main
from app.db_models import Estimate
from app.models import (
    EstimateStatus,
    InvoiceStatus,
    WorkOrderStatus,
)
from app.orchestrator import OptimusResearchOrchestrator
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_estimate_approval_api import (
    create_estimate_for_auth,
    estimate_create_payload,
    stub_estimate_job,
)
from tests.test_invoices_api import create_completed_work_order_with_invoice
from tests.test_vehicles_api import create_customer_for_auth


@pytest.mark.anyio
async def test_customer_history_requires_authenticated_session(
    settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/customers/1/history"), db_session, settings)
    assert excinfo.value.status_code == 401


@pytest.mark.anyio
async def test_customer_history_full_chain(monkeypatch, settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    work_order, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )

    history = await main.get_customer_history_record(
        invoice.customer_id, db_session, auth, limit=20
    )

    assert history.customer_id == invoice.customer_id
    assert history.customer_display_name

    assert history.estimates.total == 1
    estimate_item = history.estimates.items[0]
    assert estimate_item.status is EstimateStatus.APPROVED
    assert estimate_item.estimate_number == work_order.estimate_number
    assert estimate_item.vehicle_display_name

    assert history.work_orders.total == 1
    work_order_item = history.work_orders.items[0]
    assert work_order_item.id == work_order.id
    assert work_order_item.status is WorkOrderStatus.COMPLETED
    assert work_order_item.invoice_id == invoice.id

    assert history.invoices.total == 1
    invoice_item = history.invoices.items[0]
    assert invoice_item.id == invoice.id
    assert invoice_item.status is InvoiceStatus.DRAFT
    assert invoice_item.invoice_total == pytest.approx(invoice.invoice_total)
    assert invoice_item.balance_due == pytest.approx(invoice.invoice_total)
    assert invoice_item.is_overdue is False


@pytest.mark.anyio
async def test_customer_history_shows_declined_estimate(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    customer_id, _, estimate = await create_estimate_for_auth(settings, db_session, auth)
    estimate_model = db_session.get(Estimate, estimate.id)
    assert estimate_model is not None
    estimate_model.status = EstimateStatus.DECLINED.value
    db_session.add(estimate_model)
    db_session.commit()

    history = await main.get_customer_history_record(customer_id, db_session, auth, limit=20)

    assert history.estimates.total == 1
    assert history.estimates.items[0].status is EstimateStatus.DECLINED
    assert history.work_orders.total == 0
    assert history.invoices.total == 0


@pytest.mark.anyio
async def test_customer_history_empty_for_new_customer(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)

    history = await main.get_customer_history_record(customer_id, db_session, auth, limit=20)

    assert history.customer_id == customer_id
    assert history.estimates.items == []
    assert history.estimates.total == 0
    assert history.work_orders.items == []
    assert history.work_orders.total == 0
    assert history.invoices.items == []
    assert history.invoices.total == 0


@pytest.mark.anyio
async def test_customer_history_limit_caps_items_but_reports_full_total(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    customer_id, vehicle, _ = await create_estimate_for_auth(settings, db_session, auth)
    for _index in range(2):
        await main.create_estimate_record(
            estimate_create_payload(customer_id, vehicle.id),
            db_session,
            settings,
            auth,
        )

    history = await main.get_customer_history_record(customer_id, db_session, auth, limit=2)

    assert history.estimates.total == 3
    assert len(history.estimates.items) == 2


@pytest.mark.anyio
async def test_customer_history_cross_user_isolation(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)

    create_user(db_session, username="second-owner", password="second-password-123")
    _, other_response = await login_as(
        settings, db_session, username="second-owner", password="second-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    with pytest.raises(HTTPException) as excinfo:
        await main.get_customer_history_record(customer_id, db_session, other_auth, limit=20)
    assert excinfo.value.status_code == 404
