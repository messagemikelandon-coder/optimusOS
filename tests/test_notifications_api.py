from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
import app.work_order_store as work_order_store
from app.db_models import Notification
from app.models import (
    InvoicePaymentCreate,
    InvoicePaymentVoidRequest,
    NotificationEvent,
    PaymentAppliesTo,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
)
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_payments_api import create_completed_work_order_with_invoice, issue


async def list_for(auth, db_session, settings, *, page=1, page_size=20, unread=False):  # type: ignore[no-untyped-def]
    return await main.list_notification_records(
        db_session, settings, auth, page=page, page_size=page_size, unread=unread
    )


@pytest.mark.anyio
async def test_notifications_require_authenticated_session(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/notifications"), db_session, settings)
    assert excinfo.value.status_code == 401


@pytest.mark.anyio
async def test_full_chain_produces_expected_notification_sequence(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth)
    paid = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(
            amount=issued.invoice_total, method_label="Cash", applies_to=PaymentAppliesTo.FULL
        ),
        db_session,
        auth,
    )
    await main.void_invoice_payment(
        paid.id,
        paid.payments[0].id,
        InvoicePaymentVoidRequest(reason="Recorded in error"),
        db_session,
        auth,
    )

    listing = await list_for(auth, db_session, settings, page_size=50)
    events = [item.event for item in listing.items]
    # Newest first: void, payment, issue, then the three work-order transitions.
    assert events[0] is NotificationEvent.PAYMENT_VOIDED
    assert events[1] is NotificationEvent.PAYMENT_RECORDED
    assert events[2] is NotificationEvent.INVOICE_ISSUED
    assert events.count(NotificationEvent.WORK_ORDER_STATUS_CHANGED) == 3
    assert listing.unread_count == listing.total == len(events)
    invoice_items = [item for item in listing.items if item.entity_type.value == "invoice"]
    assert all(item.entity_id == issued.id for item in invoice_items)


@pytest.mark.anyio
async def test_customer_approval_token_path_notifies_owner(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    from app.models import (
        EstimateApprovalActionRequest,
        EstimatePaymentOptionCode,
        EstimateSendForApprovalRequest,
    )
    from app.orchestrator import OptimusResearchOrchestrator
    from tests.test_estimate_approval_api import create_estimate_for_auth, stub_estimate_job

    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, _, estimate = await create_estimate_for_auth(settings, db_session, auth)
    sent = await main.send_estimate_record_for_approval(
        estimate.id,
        EstimateSendForApprovalRequest(),
        db_session,
        auth,
        request_for(f"/api/estimates/{estimate.id}/send-for-approval", method="POST"),
    )
    token = sent.approval_link.split("token=", 1)[1]

    # Customer approves through the public token route -- no owner session.
    await main.approval_approve(
        EstimateApprovalActionRequest(
            token=token,
            revision_number=sent.revision_number,
            accepted_terms=True,
            payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
            payment_plan_acknowledged=False,
            approving_name="Casey Customer",
            typed_authorization="Casey Customer",
        ),
        db_session,
        request_for("/api/estimate-approval/approve", method="POST"),
        settings,
    )

    listing = await list_for(auth, db_session, settings)
    events = [item.event for item in listing.items]
    assert NotificationEvent.ESTIMATE_SENT in events
    assert NotificationEvent.ESTIMATE_APPROVED in events
    approved = next(
        item for item in listing.items if item.event is NotificationEvent.ESTIMATE_APPROVED
    )
    assert "Casey Customer" in approved.title
    assert approved.entity_id == estimate.id
    row = db_session.scalar(select(Notification).where(Notification.id == approved.id))
    assert row is not None
    assert row.owner_user_id == auth.user.id


@pytest.mark.anyio
async def test_unread_filter_and_mark_read_flow(monkeypatch, settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    await issue(invoice.id, db_session, settings, auth)

    unread = await list_for(auth, db_session, settings, unread=True)
    assert unread.unread_count == unread.total > 0
    first_id = unread.items[0].id

    marked = await main.mark_notification_read_record(first_id, db_session, auth)
    assert marked.ok is True
    assert marked.unread_count == unread.unread_count - 1

    # Marking the same row again is a no-op, not an error.
    remarked = await main.mark_notification_read_record(first_id, db_session, auth)
    assert remarked.unread_count == marked.unread_count

    unread_after = await list_for(auth, db_session, settings, unread=True)
    assert all(item.id != first_id for item in unread_after.items)

    all_read = await main.mark_all_notifications_read_record(db_session, auth)
    assert all_read.unread_count == 0
    final = await list_for(auth, db_session, settings, unread=True)
    assert final.items == []
    assert final.unread_count == 0


@pytest.mark.anyio
async def test_notifications_cross_user_isolation(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    await issue(invoice.id, db_session, settings, auth)
    owner_listing = await list_for(auth, db_session, settings)
    assert owner_listing.total > 0

    create_user(db_session, username="notify-other", password="other-password-123")
    _, other_response = await login_as(
        settings, db_session, username="notify-other", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    other_listing = await list_for(other_auth, db_session, settings)
    assert other_listing.items == []
    assert other_listing.total == 0
    with pytest.raises(HTTPException) as excinfo:
        await main.mark_notification_read_record(owner_listing.items[0].id, db_session, other_auth)
    assert excinfo.value.status_code == 404


@pytest.mark.anyio
async def test_idempotent_transition_adds_no_notification(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    work_order, _ = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    before = (await list_for(auth, db_session, settings)).total

    repeated = await main.update_work_order_status_record(
        work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.COMPLETED, reason="again"),
        db_session,
        auth,
    )
    assert repeated.status is WorkOrderStatus.COMPLETED
    after = (await list_for(auth, db_session, settings)).total
    assert after == before


@pytest.mark.anyio
async def test_failed_transition_rolls_back_notification(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    from tests.test_work_orders_api import create_approved_estimate_for_auth

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
    before = (await list_for(auth, db_session, settings)).total

    def boom(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("invoice generation exploded")

    monkeypatch.setattr(work_order_store, "ensure_draft_invoice_for_work_order", boom)
    with pytest.raises(RuntimeError):
        await main.update_work_order_status_record(
            work_order.id,
            WorkOrderStatusUpdate(status=WorkOrderStatus.COMPLETED, reason="Finished"),
            db_session,
            auth,
        )

    after = (await list_for(auth, db_session, settings)).total
    assert after == before


@pytest.mark.anyio
async def test_notification_pagination(monkeypatch, settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    await issue(invoice.id, db_session, settings, auth)
    total = (await list_for(auth, db_session, settings)).total
    assert total >= 4

    page_one = await list_for(auth, db_session, settings, page=1, page_size=2)
    page_two = await list_for(auth, db_session, settings, page=2, page_size=2)
    assert len(page_one.items) == 2
    assert page_one.has_more is True
    assert {item.id for item in page_one.items}.isdisjoint({item.id for item in page_two.items})

    with pytest.raises(HTTPException) as excinfo:
        await list_for(auth, db_session, settings, page_size=1000)
    assert excinfo.value.status_code == 422
