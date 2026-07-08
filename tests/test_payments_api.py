from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

import app.invoice_store as invoice_store
import app.main as main
import app.payment_store as payment_store
from app.auth import bootstrap_owner_account
from app.config import Settings
from app.db import Base, build_engine, build_session_factory
from app.db_models import Invoice, InvoicePayment, PaymentSchedule, WorkOrder
from app.models import (
    EstimatePaymentOptionCode,
    InvoiceIssueRequest,
    InvoicePaymentCreate,
    InvoicePaymentVoidRequest,
    InvoiceStatus,
    PaymentAppliesTo,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
    WorkOrderUpdate,
)
from app.orchestrator import OptimusResearchOrchestrator
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_estimate_approval_api import stub_sensitive_research_estimate_job
from tests.test_work_orders_api import create_approved_estimate_for_auth

PAYMENT_PLAN_OPTIONS = (
    EstimatePaymentOptionCode.SPLIT_PAYMENT,
    EstimatePaymentOptionCode.TWO_MONTH_PLAN,
)


async def create_completed_work_order_with_invoice(
    monkeypatch,
    settings: Settings,
    db_session,
    auth,
    *,
    payment_option: EstimatePaymentOptionCode = EstimatePaymentOptionCode.PAY_IN_FULL,
    estimate_job_stub=stub_sensitive_research_estimate_job,
    **vehicle_overrides,
):  # type: ignore[no-untyped-def]
    """Mirrors `create_completed_work_order_with_invoice` in
    `tests/test_invoices_api.py`, extended with a `payment_option` parameter so
    payment-plan work orders can be exercised. Payment-plan work orders start
    at `pending_requirements` and require `deposit_received` +
    `authorization_confirmed` before `ready_to_schedule`; tests that need to
    observe a *payment* flipping `deposit_received` reset it back to `False`
    directly on the ORM row after completion (mirroring the direct-model-edit
    style already used by `create_approved_estimate_for_auth`). Callers that
    invoke this helper more than once under the same owner in a single test
    must pass a distinct `vin` override, since VINs are unique per active
    vehicle per owner."""
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", estimate_job_stub)
    _, estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        auth,
        payment_option=payment_option,
        estimate_job_stub=estimate_job_stub,
        **vehicle_overrides,
    )
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)
    if payment_option in PAYMENT_PLAN_OPTIONS:
        await main.update_work_order_record(
            work_order.id,
            WorkOrderUpdate(deposit_received=True, authorization_confirmed=True),
            db_session,
            auth,
        )
        work_order = await main.update_work_order_status_record(
            work_order.id,
            WorkOrderStatusUpdate(status=WorkOrderStatus.READY_TO_SCHEDULE, reason="Prereqs met"),
            db_session,
            auth,
        )
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


def reset_deposit_received(db_session, work_order_id: int) -> None:
    work_order = db_session.get(WorkOrder, work_order_id)
    assert work_order is not None
    work_order.deposit_received = False
    db_session.add(work_order)
    db_session.commit()


async def issue(invoice_id: int, db_session, settings: Settings, auth, *, due_in_days: int = 30):
    return await main.issue_invoice_record(
        invoice_id,
        InvoiceIssueRequest(due_in_days=due_in_days),
        db_session,
        settings,
        auth,
    )


# 1. Full payment marks invoice paid, balance_due == 0.
@pytest.mark.anyio
async def test_full_payment_marks_invoice_paid(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth)

    updated = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(
            amount=issued.invoice_total, method_label="cash", applies_to=PaymentAppliesTo.FULL
        ),
        db_session,
        auth,
    )

    assert updated.status is InvoiceStatus.PAID
    assert updated.total_paid == issued.invoice_total
    assert updated.balance_due == 0.0


# 2. Partial payment marks invoice partially_paid, correct total_paid/balance_due.
@pytest.mark.anyio
async def test_partial_payment_marks_invoice_partially_paid(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth)

    partial_amount = 100.0
    updated = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(
            amount=partial_amount, method_label="check #100", applies_to=PaymentAppliesTo.OTHER
        ),
        db_session,
        auth,
    )

    assert updated.status is InvoiceStatus.PARTIALLY_PAID
    assert updated.total_paid == pytest.approx(partial_amount)
    assert updated.balance_due == pytest.approx(issued.invoice_total - partial_amount)


# 3. Deposit payment on a payment-plan work order flips deposit_received to True.
@pytest.mark.anyio
async def test_deposit_payment_flips_deposit_received_on_payment_plan(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    work_order, invoice = await create_completed_work_order_with_invoice(
        monkeypatch,
        settings,
        db_session,
        auth,
        payment_option=EstimatePaymentOptionCode.TWO_MONTH_PLAN,
    )
    reset_deposit_received(db_session, work_order.id)
    issued = await issue(invoice.id, db_session, settings, auth)

    await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(amount=50.0, method_label="cash", applies_to=PaymentAppliesTo.DEPOSIT),
        db_session,
        auth,
    )

    reloaded_work_order = await main.get_work_order_record(work_order.id, db_session, auth)
    assert reloaded_work_order.deposit_received is True


# 4. Deposit payment on a non-payment-plan work order does not touch deposit_received.
@pytest.mark.anyio
async def test_deposit_payment_on_pay_in_full_does_not_flip_deposit_received(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    work_order, invoice = await create_completed_work_order_with_invoice(
        monkeypatch,
        settings,
        db_session,
        auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
    )
    issued = await issue(invoice.id, db_session, settings, auth)
    assert work_order.deposit_received is False

    await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(amount=50.0, method_label="cash", applies_to=PaymentAppliesTo.DEPOSIT),
        db_session,
        auth,
    )

    reloaded_work_order = await main.get_work_order_record(work_order.id, db_session, auth)
    assert reloaded_work_order.deposit_received is False


# 5. Installment sequence (three payments) accumulates correctly, no float drift.
@pytest.mark.anyio
async def test_installment_sequence_sums_exactly_with_no_float_drift(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth)
    assert issued.invoice_total == 417.7

    for amount in (139.24, 139.23, 139.23):
        updated = await main.record_invoice_payment(
            issued.id,
            InvoicePaymentCreate(
                amount=amount, method_label="installment", applies_to=PaymentAppliesTo.INSTALLMENT
            ),
            db_session,
            auth,
        )

    assert updated.status is InvoiceStatus.PAID
    assert updated.total_paid == 417.7
    assert updated.balance_due == 0.0


# 6. Overpayment attempt is rejected 422, no row inserted, balance unchanged.
@pytest.mark.anyio
async def test_overpayment_is_rejected(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.record_invoice_payment(
            issued.id,
            InvoicePaymentCreate(
                amount=issued.invoice_total + 1,
                method_label="cash",
                applies_to=PaymentAppliesTo.FULL,
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422

    assert db_session.scalar(select(func.count()).select_from(InvoicePayment)) == 0
    unchanged = await main.get_invoice_record(issued.id, db_session, auth)
    assert unchanged.total_paid == 0.0
    assert unchanged.balance_due == issued.invoice_total


# 7. Void reverses a payment: balance restored, status recomputed back down.
@pytest.mark.anyio
async def test_void_reverses_payment_and_recomputes_status(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth)

    deposit_amount = issued.invoice_total / 2
    balance_amount = issued.invoice_total - deposit_amount
    after_deposit = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(
            amount=deposit_amount, method_label="cash", applies_to=PaymentAppliesTo.DEPOSIT
        ),
        db_session,
        auth,
    )
    deposit_payment_id = after_deposit.payments[0].id
    paid = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(
            amount=balance_amount, method_label="cash", applies_to=PaymentAppliesTo.BALANCE
        ),
        db_session,
        auth,
    )
    assert paid.status is InvoiceStatus.PAID

    voided = await main.void_invoice_payment(
        issued.id,
        deposit_payment_id,
        InvoicePaymentVoidRequest(reason="Recorded in error"),
        db_session,
        auth,
    )

    assert voided.status is InvoiceStatus.PARTIALLY_PAID
    assert voided.balance_due == pytest.approx(deposit_amount)
    assert voided.total_paid == pytest.approx(balance_amount)
    reversal_rows = [p for p in voided.payments if p.reversal_of_payment_id == deposit_payment_id]
    assert len(reversal_rows) == 1
    assert reversal_rows[0].amount == pytest.approx(-deposit_amount)
    assert reversal_rows[0].is_reversal is True


# 8. Voiding an already-voided payment is rejected 422.
@pytest.mark.anyio
async def test_voiding_already_voided_payment_is_rejected(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth)

    recorded = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(amount=50.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER),
        db_session,
        auth,
    )
    payment_id = recorded.payments[0].id
    await main.void_invoice_payment(
        issued.id, payment_id, InvoicePaymentVoidRequest(reason=None), db_session, auth
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.void_invoice_payment(
            issued.id, payment_id, InvoicePaymentVoidRequest(reason=None), db_session, auth
        )
    assert excinfo.value.status_code == 422


# 9. Voiding a reversal row itself is rejected 422.
@pytest.mark.anyio
async def test_voiding_a_reversal_row_is_rejected(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth)

    recorded = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(amount=50.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER),
        db_session,
        auth,
    )
    payment_id = recorded.payments[0].id
    voided = await main.void_invoice_payment(
        issued.id, payment_id, InvoicePaymentVoidRequest(reason=None), db_session, auth
    )
    reversal_id = next(p.id for p in voided.payments if p.reversal_of_payment_id == payment_id)

    with pytest.raises(HTTPException) as excinfo:
        await main.void_invoice_payment(
            issued.id, reversal_id, InvoicePaymentVoidRequest(reason=None), db_session, auth
        )
    assert excinfo.value.status_code == 422


# 10. Overdue calculation via now_utc monkeypatch.
@pytest.mark.anyio
async def test_overdue_calculation_uses_injected_now(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth, due_in_days=1)
    assert issued.due_at is not None

    future = issued.due_at + timedelta(days=5)
    monkeypatch.setattr(invoice_store, "now_utc", lambda: future)
    monkeypatch.setattr(payment_store, "now_utc", lambda: future)

    overdue_before_payment = await main.get_invoice_record(issued.id, db_session, auth)
    assert overdue_before_payment.status is InvoiceStatus.OVERDUE
    assert overdue_before_payment.is_overdue is True

    after_payment = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(
            amount=issued.invoice_total, method_label="cash", applies_to=PaymentAppliesTo.FULL
        ),
        db_session,
        auth,
    )
    assert after_payment.status is InvoiceStatus.PAID
    assert after_payment.is_overdue is False


# 11. Cross-user isolation: second owner gets 404 on both payment routes.
@pytest.mark.anyio
async def test_payment_routes_enforce_cross_user_isolation(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, owner_auth
    )
    issued = await issue(invoice.id, db_session, settings, owner_auth)
    recorded = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(amount=50.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER),
        db_session,
        owner_auth,
    )
    payment_id = recorded.payments[0].id

    create_user(db_session, username="other-owner", password="other-password-123")
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    with pytest.raises(HTTPException) as record_exc:
        await main.record_invoice_payment(
            issued.id,
            InvoicePaymentCreate(
                amount=1.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER
            ),
            db_session,
            other_auth,
        )
    assert record_exc.value.status_code == 404

    with pytest.raises(HTTPException) as void_exc:
        await main.void_invoice_payment(
            issued.id, payment_id, InvoicePaymentVoidRequest(reason=None), db_session, other_auth
        )
    assert void_exc.value.status_code == 404


# 12. Restart persistence: commit payments, drop session/rebuild engine, reload.
@pytest.mark.anyio
async def test_payments_persist_across_session_restart(
    monkeypatch, settings, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    db_path = tmp_path / "payments.sqlite"
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
            monkeypatch, file_settings, first_session, auth
        )
        issued = await issue(invoice.id, first_session, file_settings, auth)
        recorded = await main.record_invoice_payment(
            issued.id,
            InvoicePaymentCreate(
                amount=100.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER
            ),
            first_session,
            auth,
        )
        invoice_id = recorded.id
        assert recorded.status is InvoiceStatus.PARTIALLY_PAID
    finally:
        first_session.close()

    second_session = session_factory()
    try:
        _, response = await login_as(file_settings, second_session)
        auth = auth_context(file_settings, second_session, raw_cookie_from_response(response))
        fetched = await main.get_invoice_record(invoice_id, second_session, auth)
        assert fetched.total_paid == 100.0
        assert fetched.status is InvoiceStatus.PARTIALLY_PAID
        assert len(fetched.payments) == 1
    finally:
        second_session.close()
        Base.metadata.drop_all(bind=engine)


# 13. Payment schedule generated exactly once on issue, correct row count/amounts.
@pytest.mark.anyio
async def test_payment_schedule_generated_once_per_payment_option(
    monkeypatch, settings, db_session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    _, pay_in_full_invoice = await create_completed_work_order_with_invoice(
        monkeypatch,
        settings,
        db_session,
        auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
    )
    issued_full = await issue(pay_in_full_invoice.id, db_session, settings, auth)
    assert len(issued_full.schedule) == 1
    assert issued_full.schedule[0].label == "Full payment"
    assert issued_full.schedule[0].amount == pytest.approx(issued_full.invoice_total)

    # Re-issuing an already-issued invoice must not duplicate schedule rows.
    reissued_full = await issue(pay_in_full_invoice.id, db_session, settings, auth)
    assert len(reissued_full.schedule) == 1

    _, split_invoice = await create_completed_work_order_with_invoice(
        monkeypatch,
        settings,
        db_session,
        auth,
        payment_option=EstimatePaymentOptionCode.SPLIT_PAYMENT,
        vin="2HGFC2F59JH500001",
    )
    issued_split = await issue(split_invoice.id, db_session, settings, auth)
    assert [entry.label for entry in issued_split.schedule] == ["Deposit", "Balance"]
    assert sum(entry.amount for entry in issued_split.schedule) == pytest.approx(
        issued_split.invoice_total
    )

    _, two_month_invoice = await create_completed_work_order_with_invoice(
        monkeypatch,
        settings,
        db_session,
        auth,
        payment_option=EstimatePaymentOptionCode.TWO_MONTH_PLAN,
        vin="3VWFE21C04M000002",
    )
    issued_two_month = await issue(two_month_invoice.id, db_session, settings, auth)
    assert [entry.label for entry in issued_two_month.schedule] == [
        "Deposit",
        "Installment 1",
        "Installment 2",
    ]
    # Decimal regression: remainder is absorbed into the last row so the
    # amounts sum exactly to invoice_total even when it doesn't divide evenly.
    schedule_total = Decimal(str(issued_two_month.schedule[0].amount))
    schedule_total += Decimal(str(issued_two_month.schedule[1].amount))
    schedule_total += Decimal(str(issued_two_month.schedule[2].amount))
    assert schedule_total == Decimal(str(issued_two_month.invoice_total)).quantize(Decimal("0.01"))
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PaymentSchedule)
            .where(PaymentSchedule.invoice_id == two_month_invoice.id)
        )
        == 3
    )


# 14. Sanitized storage failure test mirroring test_invoice_storage_failures_are_sanitized.
@pytest.mark.anyio
async def test_payment_storage_failures_are_sanitized(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise SQLAlchemyError("db offline")

    monkeypatch.setattr(main, "record_payment", boom)
    with pytest.raises(HTTPException) as record_excinfo:
        await main.record_invoice_payment(
            1,
            InvoicePaymentCreate(
                amount=1.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER
            ),
            db_session,
            auth,
        )
    assert record_excinfo.value.status_code == 503
    assert record_excinfo.value.detail == "Invoice storage is unavailable."

    monkeypatch.setattr(main, "void_payment", boom)
    with pytest.raises(HTTPException) as void_excinfo:
        await main.void_invoice_payment(
            1, 1, InvoicePaymentVoidRequest(reason=None), db_session, auth
        )
    assert void_excinfo.value.status_code == 503
    assert void_excinfo.value.detail == "Invoice storage is unavailable."


# 15. Reject recording a payment against a draft invoice (must issue first).
@pytest.mark.anyio
async def test_payment_rejected_against_draft_invoice(monkeypatch, settings, db_session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    assert invoice.status is InvoiceStatus.DRAFT

    with pytest.raises(HTTPException) as excinfo:
        await main.record_invoice_payment(
            invoice.id,
            InvoicePaymentCreate(
                amount=50.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(InvoicePayment)) == 0


# 16. No float arithmetic anywhere in money paths -- `_payment_summary`/`_money`
# internals operate on Decimal, not just end-to-end float comparisons.
def test_payment_summary_and_money_helpers_use_decimal_arithmetic() -> None:
    fake_payment = SimpleNamespace(amount=Decimal("139.24"))
    fake_invoice = SimpleNamespace(
        payments=[fake_payment],
        invoice_total=417.70,
        due_at=None,
        status=InvoiceStatus.ISSUED.value,
    )
    total_paid, effective_status, is_overdue = invoice_store._payment_summary(
        cast(Invoice, fake_invoice), now=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert isinstance(total_paid, Decimal)
    assert total_paid == Decimal("139.24")
    assert effective_status is InvoiceStatus.PARTIALLY_PAID
    assert is_overdue is False

    money_value = invoice_store._money(417.70)
    assert isinstance(money_value, Decimal)
    assert money_value == Decimal("417.70")

    derived = invoice_store.derive_invoice_status(
        invoice_total=Decimal("417.70"),
        total_paid=Decimal("417.70"),
        due_at=None,
        current_status=InvoiceStatus.ISSUED,
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert isinstance(derived, InvoiceStatus)
    assert derived is InvoiceStatus.PAID
