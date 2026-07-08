from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main as main
from app.db_models import InvoicePayment, WorkOrderStatusEvent
from app.models import (
    InvoicePaymentCreate,
    PaymentAppliesTo,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
)
from tests.test_context_api import auth_context, login_as, raw_cookie_from_response
from tests.test_payments_api import create_completed_work_order_with_invoice, issue

pytestmark = pytest.mark.anyio


async def test_repeated_status_transition_does_not_duplicate_status_events(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    """Phase 4 deliverable 6 (idempotency audit): re-firing the exact same
    status-transition payload twice must not append a second status event.
    `transition_work_order_status` already short-circuits on
    `target_status == current_status` before appending an event; this test
    proves that behavior rather than assuming it. Overlaps
    `test_duplicate_completion_does_not_duplicate_invoice` in
    `tests/test_invoices_api.py`, which repeats the same COMPLETED->COMPLETED
    call but asserts on invoice-row count instead of status-event count --
    kept as a distinct assertion, not new logic coverage."""
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth, vin="1FTFW1ET5BFA00003"
    )
    work_order_id = invoice.work_order_id

    first = await main.update_work_order_status_record(
        work_order_id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.COMPLETED, reason="repeat me"),
        db_session,
        auth,
    )
    events_after_first = db_session.scalar(
        select(func.count())
        .select_from(WorkOrderStatusEvent)
        .where(WorkOrderStatusEvent.work_order_id == work_order_id)
    )

    second = await main.update_work_order_status_record(
        work_order_id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.COMPLETED, reason="repeat me again"),
        db_session,
        auth,
    )
    events_after_second = db_session.scalar(
        select(func.count())
        .select_from(WorkOrderStatusEvent)
        .where(WorkOrderStatusEvent.work_order_id == work_order_id)
    )

    assert first.status is WorkOrderStatus.COMPLETED
    assert second.status is WorkOrderStatus.COMPLETED
    assert events_after_second == events_after_first


async def test_repeated_issue_does_not_duplicate_invoice_or_schedule(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    """Re-firing `issue` on an already-issued invoice must not re-stamp
    `issued_at`/`due_at` or regenerate the payment schedule."""
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth, vin="1FTFW1ET5BFA00004"
    )

    first_issue = await issue(invoice.id, db_session, settings, auth)
    second_issue = await issue(invoice.id, db_session, settings, auth)

    assert second_issue.issued_at == first_issue.issued_at
    assert second_issue.due_at == first_issue.due_at
    assert len(second_issue.schedule) == len(first_issue.schedule)


async def test_repeated_full_payment_request_is_rejected_not_duplicated(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    """Re-submitting the exact same full-payment request after the invoice
    is already paid must be rejected as an overpayment, not silently
    inserted as a second payment row."""
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth, vin="1FTFW1ET5BFA00005"
    )
    issued = await issue(invoice.id, db_session, settings, auth)
    payload = InvoicePaymentCreate(
        amount=issued.invoice_total, method_label="Cash", applies_to=PaymentAppliesTo.FULL
    )

    paid = await main.record_invoice_payment(issued.id, payload, db_session, auth)
    assert paid.status.value == "paid"
    payment_count_after_first = db_session.scalar(
        select(func.count())
        .select_from(InvoicePayment)
        .where(InvoicePayment.invoice_id == issued.id)
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        await main.record_invoice_payment(issued.id, payload, db_session, auth)
    assert excinfo.value.status_code == 422
    payment_count_after_second_attempt = db_session.scalar(
        select(func.count())
        .select_from(InvoicePayment)
        .where(InvoicePayment.invoice_id == issued.id)
    )

    assert payment_count_after_second_attempt == payment_count_after_first
