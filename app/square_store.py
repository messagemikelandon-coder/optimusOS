from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.auth import AuthContext, ensure_utc
from app.db_models import Invoice
from app.invoice_store import (
    InvoiceNotFoundError,
    _money,
    _require_invoice,
    _to_read,
)
from app.models import InvoiceRead, InvoiceStatus
from app.services.square import SquareInvoiceClient

__all__ = [
    "InvoiceNotFoundError",
    "SquareAlreadyPushedError",
    "SquareStoreError",
    "push_invoice_to_square",
    "refresh_square_invoice",
]


class SquareStoreError(ValueError):
    pass


class SquareAlreadyPushedError(SquareStoreError):
    pass


def _to_cents(amount: float | Decimal) -> int:
    # Decimal end-to-end; never int(float * 100).
    return int((_money(amount) * 100).to_integral_value())


def _due_date(value: Any) -> str | None:
    if value is None:
        return None
    return ensure_utc(value).date().isoformat()


def _payment_requests(invoice: Invoice) -> list[dict[str, Any]]:
    """Map our payment_schedules rows onto Square payment requests. Square's
    INSTALLMENT request type requires the paid Invoices Plus tier, so multi-row
    schedules collapse to DEPOSIT (first row) + BALANCE (final due date); the
    middle rows are described in the invoice description instead."""
    rows = sorted(invoice.schedule, key=lambda row: row.sort_order)
    balance_due_date = _due_date(invoice.due_at) or _due_date(rows[-1].due_at if rows else None)
    if len(rows) <= 1:
        request: dict[str, Any] = {"request_type": "BALANCE"}
        if balance_due_date:
            request["due_date"] = balance_due_date
        return [request]
    deposit_row = rows[0]
    deposit: dict[str, Any] = {
        "request_type": "DEPOSIT",
        "fixed_amount_requested_money": {
            "amount": _to_cents(deposit_row.amount),
            "currency": "USD",
        },
    }
    deposit_due = _due_date(deposit_row.due_at)
    if deposit_due:
        deposit["due_date"] = deposit_due
    balance: dict[str, Any] = {"request_type": "BALANCE"}
    final_due = _due_date(rows[-1].due_at) or balance_due_date
    if final_due:
        balance["due_date"] = final_due
    return [deposit, balance]


def _schedule_description(invoice: Invoice) -> str:
    rows = sorted(invoice.schedule, key=lambda row: row.sort_order)
    if len(rows) <= 2:
        return f"OptimusOS invoice {invoice.invoice_number}."
    lines = [f"OptimusOS invoice {invoice.invoice_number}. Payment schedule:"]
    for row in rows:
        due = _due_date(row.due_at)
        lines.append(f"- {row.label}: ${_money(row.amount):.2f}" + (f" due {due}" if due else ""))
    lines.append(
        "Square collects the deposit and final balance; middle installments are informational."
    )
    return "\n".join(lines)


def _apply_square_fields(invoice: Invoice, square_invoice: dict[str, Any]) -> None:
    invoice.square_invoice_id = str(square_invoice.get("id") or "") or invoice.square_invoice_id
    status_value = str(square_invoice.get("status") or "")
    if status_value:
        invoice.square_status = status_value[:40]
    url = str(square_invoice.get("public_url") or "")
    if url:
        invoice.square_payment_url = url[:500]


def push_invoice_to_square(
    *,
    db: Session,
    auth: AuthContext,
    invoice_id: int,
    client: SquareInvoiceClient,
    location_id: str,
) -> InvoiceRead:
    invoice = _require_invoice(db, auth, invoice_id)
    current_status = InvoiceStatus(invoice.status)
    if current_status in (InvoiceStatus.DRAFT, InvoiceStatus.VOID):
        raise SquareStoreError("Only issued invoices can be sent to Square.")
    if invoice.square_invoice_id:
        raise SquareAlreadyPushedError(
            "Invoice was already sent to Square. Use refresh to update its status."
        )
    email = (invoice.customer_snapshot or {}).get("email")
    if not email:
        raise SquareStoreError(
            "The invoice's customer snapshot has no email address; Square invoices are "
            "delivered by email."
        )
    display_name = (invoice.customer_snapshot or {}).get("display_name") or "Customer"
    phone = (invoice.customer_snapshot or {}).get("phone")

    customer = client.search_customer_by_email(str(email))
    if customer is None:
        customer = client.create_customer(
            idempotency_key=f"{invoice.invoice_number}:customer",
            given_name=str(display_name),
            email=str(email),
            phone=str(phone) if phone else None,
        )
    order = client.create_order(
        idempotency_key=f"{invoice.invoice_number}:order",
        location_id=location_id,
        reference_id=invoice.invoice_number,
        line_name=f"Invoice {invoice.invoice_number} — {invoice.title}"[:255],
        amount_cents=_to_cents(invoice.invoice_total),
    )
    created = client.create_invoice(
        idempotency_key=f"{invoice.invoice_number}:invoice",
        location_id=location_id,
        order_id=str(order["id"]),
        customer_id=str(customer["id"]),
        title=f"{invoice.invoice_number} — {invoice.title}",
        description=_schedule_description(invoice),
        payment_requests=_payment_requests(invoice),
    )
    published = client.publish_invoice(
        square_invoice_id=str(created["id"]),
        version=int(created.get("version", 0)),
        idempotency_key=f"{invoice.invoice_number}:publish",
    )
    # Columns are persisted only after the full sequence succeeds -- a failure
    # anywhere above leaves the invoice unpushed and safely retryable.
    _apply_square_fields(invoice, published)
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return _to_read(invoice)


def refresh_square_invoice(
    *,
    db: Session,
    auth: AuthContext,
    invoice_id: int,
    client: SquareInvoiceClient,
) -> InvoiceRead:
    invoice = _require_invoice(db, auth, invoice_id)
    if not invoice.square_invoice_id:
        raise SquareStoreError("Invoice has not been sent to Square yet.")
    square_invoice = client.get_invoice(invoice.square_invoice_id)
    _apply_square_fields(invoice, square_invoice)
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return _to_read(invoice)
