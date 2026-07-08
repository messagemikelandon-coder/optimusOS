from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import AuthContext, ensure_utc
from app.config import Settings
from app.db_models import Invoice, InvoiceLineItem, WorkOrder
from app.estimate_store import _revision_to_approval_view
from app.models import (
    EstimateApprovalRevisionView,
    EstimateFeeItem,
    EstimateLaborItem,
    InvoiceCustomerSnapshot,
    InvoiceIssueRequest,
    InvoiceLineItemKind,
    InvoiceLineItemRead,
    InvoiceListResponse,
    InvoiceRead,
    InvoiceStatus,
    InvoiceVehicleSnapshot,
    SelectedPart,
    WorkOrderStatus,
)


class InvoiceStoreError(ValueError):
    pass


class InvoiceNotFoundError(InvoiceStoreError):
    pass


def _invoice_query(auth: AuthContext) -> Select[tuple[Invoice]]:
    return select(Invoice).where(Invoice.owner_user_id == auth.user.id)


def _require_invoice(db: Session, auth: AuthContext, invoice_id: int) -> Invoice:
    invoice = db.scalar(_invoice_query(auth).where(Invoice.id == invoice_id))
    if invoice is None:
        raise InvoiceNotFoundError("Invoice not found.")
    return invoice


def _safe_customer_snapshot(snapshot: dict[str, Any]) -> InvoiceCustomerSnapshot:
    return InvoiceCustomerSnapshot.model_validate(
        {
            "display_name": snapshot.get("display_name", "Unknown customer"),
            "email": snapshot.get("email"),
            "phone": snapshot.get("phone"),
        }
    )


def _safe_vehicle_snapshot(snapshot: dict[str, Any]) -> InvoiceVehicleSnapshot:
    return InvoiceVehicleSnapshot.model_validate(
        {
            "display_name": snapshot.get("display_name", "Unknown vehicle"),
            "vin": snapshot.get("vin"),
            "license_plate": snapshot.get("license_plate"),
            "current_mileage": snapshot.get("current_mileage"),
        }
    )


def _line_item_to_read(item: InvoiceLineItem) -> InvoiceLineItemRead:
    return InvoiceLineItemRead(
        id=item.id,
        sort_order=item.sort_order,
        kind=InvoiceLineItemKind(item.kind),
        description=item.description,
        quantity=item.quantity,
        unit_amount=item.unit_amount,
        line_total=item.line_total,
    )


def _to_read(invoice: Invoice) -> InvoiceRead:
    return InvoiceRead(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        status=InvoiceStatus(invoice.status),
        work_order_id=invoice.work_order_id,
        estimate_id=invoice.estimate_id,
        estimate_revision_id=invoice.estimate_revision_id,
        customer_id=invoice.customer_id,
        vehicle_id=invoice.vehicle_id,
        customer=_safe_customer_snapshot(invoice.customer_snapshot),
        vehicle=_safe_vehicle_snapshot(invoice.vehicle_snapshot),
        title=invoice.title,
        complaint=invoice.complaint,
        payment_option_selected=invoice.payment_option_selected,
        issued_at=ensure_utc(invoice.issued_at) if invoice.issued_at else None,
        due_at=ensure_utc(invoice.due_at) if invoice.due_at else None,
        labor_total=invoice.labor_total,
        parts_total=invoice.parts_total,
        fees_total=invoice.fees_total,
        invoice_total=invoice.invoice_total,
        line_items=[_line_item_to_read(item) for item in invoice.line_items],
        created_at=ensure_utc(invoice.created_at),
        updated_at=ensure_utc(invoice.updated_at),
    )


def _revision_view_for_invoice(work_order: WorkOrder) -> EstimateApprovalRevisionView:
    return _revision_to_approval_view(work_order.revision)


def _invoice_line_payloads(
    revision_view: EstimateApprovalRevisionView,
) -> list[dict[str, float | int | str]]:
    payloads: list[dict[str, float | int | str]] = []
    sort_order = 1
    for labor in revision_view.estimate.labor_items:
        labor_item = EstimateLaborItem.model_validate(labor)
        payloads.append(
            {
                "sort_order": sort_order,
                "kind": InvoiceLineItemKind.LABOR.value,
                "description": labor_item.description,
                "quantity": labor_item.labor_hours,
                "unit_amount": labor_item.labor_rate,
                "line_total": labor_item.labor_total,
            }
        )
        sort_order += 1
    for part in revision_view.estimate.selected_parts:
        selected_part = SelectedPart.model_validate(part)
        payloads.append(
            {
                "sort_order": sort_order,
                "kind": InvoiceLineItemKind.PART.value,
                "description": selected_part.part_name,
                "quantity": float(selected_part.quantity),
                "unit_amount": selected_part.unit_price,
                "line_total": selected_part.extended_price,
            }
        )
        sort_order += 1
    for fee in revision_view.estimate.fee_items:
        fee_item = EstimateFeeItem.model_validate(fee)
        payloads.append(
            {
                "sort_order": sort_order,
                "kind": InvoiceLineItemKind.FEE.value,
                "description": fee_item.label,
                "quantity": 1.0,
                "unit_amount": fee_item.amount,
                "line_total": fee_item.amount,
            }
        )
        sort_order += 1
    return payloads


def _invoice_fees_total(revision_view: EstimateApprovalRevisionView) -> float:
    return float(
        sum(EstimateFeeItem.model_validate(item).amount for item in revision_view.estimate.fee_items)
    )


def ensure_draft_invoice_for_work_order(
    *,
    db: Session,
    auth: AuthContext,
    work_order: WorkOrder,
) -> InvoiceRead:
    if invoice := work_order.invoice:
        return _to_read(invoice)
    if work_order.status != WorkOrderStatus.COMPLETED.value:
        raise InvoiceStoreError("Only completed work orders can generate invoices.")

    revision_view = _revision_view_for_invoice(work_order)
    existing = db.scalar(_invoice_query(auth).where(Invoice.work_order_id == work_order.id))
    if existing is not None:
        return _to_read(existing)

    line_item_payloads = _invoice_line_payloads(revision_view)
    totals = revision_view.estimate.totals
    customer = revision_view.customer
    vehicle = revision_view.vehicle
    invoice = Invoice(
        owner_user_id=auth.user.id,
        work_order_id=work_order.id,
        estimate_id=work_order.estimate_id,
        estimate_revision_id=work_order.estimate_revision_id,
        customer_id=work_order.customer_id,
        vehicle_id=work_order.vehicle_id,
        invoice_number="",
        status=InvoiceStatus.DRAFT.value,
        title=work_order.title,
        complaint=work_order.complaint,
        payment_option_selected=work_order.payment_option_selected,
        customer_snapshot=customer.model_dump(mode="json"),
        vehicle_snapshot=vehicle.model_dump(mode="json"),
        labor_total=totals.labor_total,
        parts_total=totals.parts_subtotal,
        fees_total=_invoice_fees_total(revision_view),
        invoice_total=totals.estimated_total,
    )
    db.add(invoice)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(_invoice_query(auth).where(Invoice.work_order_id == work_order.id))
        if existing is None:
            raise
        return _to_read(existing)

    invoice.invoice_number = f"INV-{invoice.id:05d}"
    db.add(invoice)
    for payload in line_item_payloads:
        db.add(
            InvoiceLineItem(
                invoice_id=invoice.id,
                sort_order=int(payload["sort_order"]),
                kind=str(payload["kind"]),
                description=str(payload["description"]),
                quantity=float(payload["quantity"]),
                unit_amount=float(payload["unit_amount"]),
                line_total=float(payload["line_total"]),
            )
        )
    db.commit()
    db.refresh(invoice)
    return _to_read(invoice)


def list_invoices(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    status: InvoiceStatus | None,
    search: str | None,
) -> InvoiceListResponse:
    if page_size > settings.invoices_max_page_size:
        raise InvoiceStoreError(
            f"Page size exceeds the maximum of {settings.invoices_max_page_size}."
        )
    if page < 1:
        raise InvoiceStoreError("Page must be 1 or greater.")
    query = _invoice_query(auth)
    if status is not None:
        query = query.where(Invoice.status == status.value)
    if search:
        token = search.strip().lower()
        if token:
            query = query.where(
                or_(
                    func.lower(Invoice.invoice_number).contains(token),
                    func.lower(Invoice.title).contains(token),
                )
            )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    items = db.scalars(
        query.order_by(Invoice.updated_at.desc(), Invoice.id.desc()).offset(offset).limit(page_size)
    ).all()
    return InvoiceListResponse(
        items=[_to_read(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(items) < total,
    )


def get_invoice(*, db: Session, auth: AuthContext, invoice_id: int) -> InvoiceRead:
    return _to_read(_require_invoice(db, auth, invoice_id))


def issue_invoice(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    invoice_id: int,
    payload: InvoiceIssueRequest,
) -> InvoiceRead:
    del settings
    invoice = _require_invoice(db, auth, invoice_id)
    current_status = InvoiceStatus(invoice.status)
    if current_status is InvoiceStatus.ISSUED:
        return _to_read(invoice)
    if current_status is not InvoiceStatus.DRAFT:
        raise InvoiceStoreError("Only draft invoices can be issued.")
    issued_at = datetime.now(UTC)
    invoice.status = InvoiceStatus.ISSUED.value
    invoice.issued_at = issued_at
    invoice.due_at = issued_at + timedelta(days=payload.due_in_days)
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return _to_read(invoice)


def render_invoice_html(invoice: InvoiceRead, *, business_name: str) -> str:
    rows = "".join(
        (
            "<tr>"
            f"<td>{escape(item.kind.value.replace('_', ' ').title())}</td>"
            f"<td>{escape(item.description)}</td>"
            f"<td>{item.quantity:g}</td>"
            f"<td>${item.unit_amount:,.2f}</td>"
            f"<td>${item.line_total:,.2f}</td>"
            "</tr>"
        )
        for item in invoice.line_items
    )
    status_label = invoice.status.value.replace("_", " ").title()
    due_at = invoice.due_at.isoformat() if invoice.due_at else "Not issued"
    issued_at = invoice.issued_at.isoformat() if invoice.issued_at else "Draft"
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>{escape(invoice.invoice_number)} - {escape(business_name)}</title>
    <link rel="stylesheet" href="/static/invoice.css">
  </head>
  <body>
    <header>
      <div>
        <h1>{escape(business_name)}</h1>
        <p class="muted">Customer-facing invoice generated from a completed work order.</p>
      </div>
      <div>
        <h2>{escape(invoice.invoice_number)}</h2>
        <p>Status: {escape(status_label)}</p>
      </div>
    </header>
    <section class="meta">
      <div class="card">
        <h3>Customer</h3>
        <p><strong>{escape(invoice.customer.display_name)}</strong></p>
        <p>{escape(invoice.customer.email or "No email on file")}</p>
        <p>{escape(invoice.customer.phone or "No phone on file")}</p>
      </div>
      <div class="card">
        <h3>Vehicle</h3>
        <p><strong>{escape(invoice.vehicle.display_name)}</strong></p>
        <p>{escape(invoice.vehicle.vin or "VIN not listed")}</p>
        <p>{escape(invoice.vehicle.license_plate or "Plate not listed")}</p>
      </div>
      <div class="card">
        <h3>Repair</h3>
        <p><strong>{escape(invoice.title)}</strong></p>
        <p>{escape(invoice.complaint)}</p>
      </div>
      <div class="card">
        <h3>Issue and due dates</h3>
        <p>Issued: {escape(issued_at)}</p>
        <p>Due: {escape(due_at)}</p>
      </div>
    </section>
    <table>
      <thead>
        <tr>
          <th>Kind</th>
          <th>Description</th>
          <th>Qty</th>
          <th>Unit</th>
          <th>Total</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    <section class="totals">
      <div class="card"><span class="muted">Labor total</span><strong>${invoice.labor_total:,.2f}</strong></div>
      <div class="card"><span class="muted">Parts total</span><strong>${invoice.parts_total:,.2f}</strong></div>
      <div class="card"><span class="muted">Fees total</span><strong>${invoice.fees_total:,.2f}</strong></div>
      <div class="card"><span class="muted">Invoice total</span><strong>${invoice.invoice_total:,.2f}</strong></div>
    </section>
  </body>
</html>"""


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_line_fragments(value: str, *, width: int = 110) -> list[str]:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    fragments: list[str] = []
    for segment in normalized.split("\n"):
        cleaned = " ".join(segment.split())
        if not cleaned:
            continue
        fragments.extend(
            textwrap.wrap(
                cleaned,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
            )
        )
    return fragments or [""]


def _pdf_text_lines(invoice: InvoiceRead, *, business_name: str) -> list[str]:
    lines = [
        business_name,
        f"Invoice {invoice.invoice_number}",
        f"Status: {invoice.status.value.replace('_', ' ').title()}",
        f"Customer: {invoice.customer.display_name}",
        f"Vehicle: {invoice.vehicle.display_name}",
        f"Complaint: {invoice.complaint}",
        f"Issued: {invoice.issued_at.isoformat() if invoice.issued_at else 'Draft'}",
        f"Due: {invoice.due_at.isoformat() if invoice.due_at else 'Not issued'}",
        "Line items:",
    ]
    for item in invoice.line_items:
        lines.append(
            f"{item.kind.value.title()} | {item.description} | qty {item.quantity:g} | "
            f"unit ${item.unit_amount:,.2f} | total ${item.line_total:,.2f}"
        )
    lines.extend(
        [
            f"Labor total: ${invoice.labor_total:,.2f}",
            f"Parts total: ${invoice.parts_total:,.2f}",
            f"Fees total: ${invoice.fees_total:,.2f}",
            f"Invoice total: ${invoice.invoice_total:,.2f}",
        ]
    )
    return lines


def render_invoice_pdf(invoice: InvoiceRead, *, business_name: str) -> bytes:
    lines = _pdf_text_lines(invoice, business_name=business_name)
    content_lines = ["BT", "/F1 11 Tf", "50 780 Td", "14 TL"]
    for line in lines:
        for fragment in _pdf_line_fragments(line):
            content_lines.append(f"({_pdf_escape(fragment)}) Tj")
            content_lines.append("T*")
    content_lines.append("ET")
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj"
        ),
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
        f"5 0 obj << /Length {len(stream)} >> stream\n".encode("ascii")
        + stream
        + b"\nendstream endobj",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
        pdf.extend(b"\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )
    return bytes(pdf)
