from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext
from app.customer_store import (
    CustomerNotFoundError,
    CustomerStoreError,
    display_name,
    get_customer_model,
)
from app.db_models import Estimate, Invoice, WorkOrder
from app.invoice_store import _money, _payment_summary, now_utc
from app.models import (
    CustomerHistoryEstimateItem,
    CustomerHistoryEstimateSection,
    CustomerHistoryInvoiceItem,
    CustomerHistoryInvoiceSection,
    CustomerHistoryResponse,
    CustomerHistoryWorkOrderItem,
    CustomerHistoryWorkOrderSection,
    EstimateStatus,
    WorkOrderStatus,
)
from app.vehicle_store import vehicle_display_name

__all__ = [
    "CustomerNotFoundError",
    "CustomerStoreError",
    "get_customer_history",
]


def _estimate_item(estimate: Estimate) -> CustomerHistoryEstimateItem:
    return CustomerHistoryEstimateItem(
        id=estimate.id,
        estimate_number=estimate.estimate_number,
        status=EstimateStatus(estimate.status),
        vehicle_display_name=vehicle_display_name(estimate.vehicle),
        estimate_total=estimate.estimate_total,
        created_at=estimate.created_at,
        updated_at=estimate.updated_at,
    )


def _work_order_item(work_order: WorkOrder) -> CustomerHistoryWorkOrderItem:
    return CustomerHistoryWorkOrderItem(
        id=work_order.id,
        estimate_number=work_order.estimate_number,
        title=work_order.title,
        status=WorkOrderStatus(work_order.status),
        invoice_id=work_order.invoice.id if work_order.invoice else None,
        updated_at=work_order.updated_at,
    )


def _invoice_item(invoice: Invoice) -> CustomerHistoryInvoiceItem:
    total_paid, effective_status, is_overdue = _payment_summary(invoice, now=now_utc())
    invoice_total = _money(invoice.invoice_total)
    balance_due = max(invoice_total - total_paid, Decimal("0.00"))
    return CustomerHistoryInvoiceItem(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        status=effective_status,
        invoice_total=float(invoice_total),
        balance_due=float(balance_due),
        is_overdue=is_overdue,
        issued_at=invoice.issued_at,
        due_at=invoice.due_at,
    )


def get_customer_history(
    *,
    db: Session,
    auth: AuthContext,
    customer_id: int,
    limit: int,
) -> CustomerHistoryResponse:
    customer = get_customer_model(db=db, auth=auth, customer_id=customer_id)

    estimate_where = (
        Estimate.owner_user_id == auth.user.id,
        Estimate.customer_id == customer.id,
    )
    work_order_where = (
        WorkOrder.owner_user_id == auth.user.id,
        WorkOrder.customer_id == customer.id,
    )
    invoice_where = (
        Invoice.owner_user_id == auth.user.id,
        Invoice.customer_id == customer.id,
    )

    estimates = list(
        db.scalars(
            select(Estimate)
            .where(*estimate_where)
            .order_by(Estimate.updated_at.desc(), Estimate.id.desc())
            .limit(limit)
        )
    )
    work_orders = list(
        db.scalars(
            select(WorkOrder)
            .where(*work_order_where)
            .order_by(WorkOrder.updated_at.desc(), WorkOrder.id.desc())
            .limit(limit)
        )
    )
    invoices = list(
        db.scalars(
            select(Invoice)
            .where(*invoice_where)
            .order_by(Invoice.updated_at.desc(), Invoice.id.desc())
            .limit(limit)
        )
    )

    estimate_total = db.scalar(select(func.count()).select_from(Estimate).where(*estimate_where))
    work_order_total = db.scalar(
        select(func.count()).select_from(WorkOrder).where(*work_order_where)
    )
    invoice_total = db.scalar(select(func.count()).select_from(Invoice).where(*invoice_where))

    return CustomerHistoryResponse(
        customer_id=customer.id,
        customer_display_name=display_name(customer),
        estimates=CustomerHistoryEstimateSection(
            items=[_estimate_item(estimate) for estimate in estimates],
            total=int(estimate_total or 0),
        ),
        work_orders=CustomerHistoryWorkOrderSection(
            items=[_work_order_item(work_order) for work_order in work_orders],
            total=int(work_order_total or 0),
        ),
        invoices=CustomerHistoryInvoiceSection(
            items=[_invoice_item(invoice) for invoice in invoices],
            total=int(invoice_total or 0),
        ),
    )
