from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, ensure_utc
from app.db_models import Invoice, InvoicePayment
from app.invoice_store import (
    InvoiceNotFoundError,
    InvoiceStoreError,
    _money,
    _payment_summary,
    _require_invoice,
    _to_read,
    derive_invoice_status,
    now_utc,
)
from app.models import (
    InvoicePaymentCreate,
    InvoicePaymentVoidRequest,
    InvoiceRead,
    InvoiceStatus,
    NotificationEntityType,
    NotificationEvent,
    PaymentAppliesTo,
)
from app.notification_store import record_notification
from app.work_order_store import PAYMENT_PLAN_OPTIONS

__all__ = [
    "InvoiceNotFoundError",
    "InvoiceStoreError",
    "PaymentNotFoundError",
    "record_payment",
    "void_payment",
]


class PaymentNotFoundError(InvoiceStoreError):
    pass


def _payment_query(invoice_id: int, auth: AuthContext) -> Select[tuple[InvoicePayment]]:
    return select(InvoicePayment).where(
        InvoicePayment.owner_user_id == auth.user.id,
        InvoicePayment.invoice_id == invoice_id,
    )


def record_payment(
    *,
    db: Session,
    auth: AuthContext,
    invoice_id: int,
    payload: InvoicePaymentCreate,
) -> InvoiceRead:
    invoice = _require_invoice(db, auth, invoice_id)
    # Lock the invoice row for the rest of this transaction so concurrent
    # payment submissions against the same invoice serialize instead of both
    # reading the same pre-payment total and both passing the overpayment
    # check below.
    db.execute(select(Invoice.id).where(Invoice.id == invoice.id).with_for_update())
    current_status = InvoiceStatus(invoice.status)
    if current_status in (InvoiceStatus.DRAFT, InvoiceStatus.VOID):
        raise InvoiceStoreError("Payments can only be recorded against issued invoices.")

    amount = _money(payload.amount)
    if amount <= 0:
        raise InvoiceStoreError("Payment amount must be greater than zero.")

    now = now_utc()
    total_paid_before, _, _ = _payment_summary(invoice, now=now)
    invoice_total = _money(invoice.invoice_total)
    if total_paid_before + amount > invoice_total:
        # Strict, no tolerance. Corrections are void + re-record only.
        raise InvoiceStoreError("Payment would exceed the invoice balance due.")

    recorded_at = ensure_utc(payload.recorded_at) if payload.recorded_at else now
    payment = InvoicePayment(
        owner_user_id=auth.user.id,
        invoice_id=invoice.id,
        amount=amount,
        applies_to=payload.applies_to.value,
        method_label=payload.method_label,
        note=payload.note,
        recorded_at=recorded_at,
        created_by_user_id=auth.user.id,
    )
    db.add(payment)

    # Deposit-satisfies-prerequisite: a deposit payment on a payment-plan work
    # order flips `deposit_received` in the same transaction. Voiding this
    # payment later does NOT auto-revert it -- documented limitation, not a
    # silent gap; the owner can flip it back via PATCH /api/work-orders/{id}.
    if payload.applies_to is PaymentAppliesTo.DEPOSIT:
        work_order = invoice.work_order
        if (
            work_order.payment_option_selected or ""
        ) in PAYMENT_PLAN_OPTIONS and not work_order.deposit_received:
            work_order.deposit_received = True
            db.add(work_order)

    new_total_paid = total_paid_before + amount
    new_status = derive_invoice_status(
        invoice_total=invoice_total,
        total_paid=new_total_paid,
        due_at=ensure_utc(invoice.due_at) if invoice.due_at else None,
        current_status=current_status,
        now=now,
    )
    # Best-effort physical-column cache, updated only on this write path; the
    # detail view (`_to_read`) always recomputes fresh regardless.
    invoice.status = new_status.value
    db.add(invoice)
    deposit_note = (
        " Deposit requirement satisfied on the linked work order."
        if payload.applies_to is PaymentAppliesTo.DEPOSIT
        else ""
    )
    record_notification(
        db=db,
        owner_user_id=invoice.owner_user_id,
        entity_type=NotificationEntityType.INVOICE,
        entity_id=invoice.id,
        event=NotificationEvent.PAYMENT_RECORDED,
        title=f"Payment of ${amount:.2f} recorded on invoice {invoice.invoice_number}",
        body=f"Invoice status: {new_status.value}.{deposit_note}",
    )
    db.commit()
    db.refresh(invoice)
    return _to_read(invoice)


def void_payment(
    *,
    db: Session,
    auth: AuthContext,
    invoice_id: int,
    payment_id: int,
    payload: InvoicePaymentVoidRequest,
) -> InvoiceRead:
    invoice = _require_invoice(db, auth, invoice_id)
    payment = db.scalar(_payment_query(invoice.id, auth).where(InvoicePayment.id == payment_id))
    if payment is None:
        raise PaymentNotFoundError("Payment not found.")
    if payment.reversal_of_payment_id is not None:
        raise InvoiceStoreError("Cannot void a reversal row.")
    already_voided = db.scalar(
        _payment_query(invoice.id, auth).where(InvoicePayment.reversal_of_payment_id == payment.id)
    )
    if already_voided is not None:
        raise InvoiceStoreError("Payment has already been voided.")

    now = now_utc()
    reversal_amount = -_money(payment.amount)
    reversal = InvoicePayment(
        owner_user_id=auth.user.id,
        invoice_id=invoice.id,
        amount=reversal_amount,
        applies_to=payment.applies_to,
        method_label=payment.method_label,
        note=payload.reason,
        recorded_at=now,
        reversal_of_payment_id=payment.id,
        created_by_user_id=auth.user.id,
    )
    db.add(reversal)

    current_status = InvoiceStatus(invoice.status)
    total_paid_before, _, _ = _payment_summary(invoice, now=now)
    new_total_paid = total_paid_before + reversal_amount
    new_status = derive_invoice_status(
        invoice_total=_money(invoice.invoice_total),
        total_paid=new_total_paid,
        due_at=ensure_utc(invoice.due_at) if invoice.due_at else None,
        current_status=current_status,
        now=now,
    )
    invoice.status = new_status.value
    db.add(invoice)
    record_notification(
        db=db,
        owner_user_id=invoice.owner_user_id,
        entity_type=NotificationEntityType.INVOICE,
        entity_id=invoice.id,
        event=NotificationEvent.PAYMENT_VOIDED,
        title=f"Payment of ${_money(payment.amount):.2f} voided on invoice {invoice.invoice_number}",
        body=f"Invoice status: {new_status.value}.",
    )
    db.commit()
    db.refresh(invoice)
    return _to_read(invoice)
