from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import AuthContext, effective_owner_id, ensure_utc
from app.db_models import (
    Estimate,
    EstimateApprovalRequest,
    Invoice,
    PartAllocation,
    PartAllocationEvent,
    WorkOrder,
    WorkOrderStatusEvent,
)
from app.invoice_store import _money, _payment_summary, now_utc
from app.models import (
    DashboardCurrentOperations,
    DashboardFinancialObligations,
    DashboardInsight,
    DashboardInsightPriority,
    DashboardMetric,
    DashboardRevenueBreakdownItem,
    DashboardSummaryResponse,
    DashboardTrendPoint,
    DashboardUpcomingInstallment,
    DashboardWorkOrderStatusCount,
    EstimateStatus,
    InvoiceStatus,
    WorkOrderStatus,
)

__all__ = ["get_dashboard_summary"]

_ISSUED_INVOICE_STATUSES = (
    InvoiceStatus.ISSUED,
    InvoiceStatus.PARTIALLY_PAID,
    InvoiceStatus.PAID,
    InvoiceStatus.OVERDUE,
)
_OPEN_INVOICE_STATUSES = (
    InvoiceStatus.ISSUED,
    InvoiceStatus.PARTIALLY_PAID,
    InvoiceStatus.OVERDUE,
)
_STALLED_WAITING_FOR_PARTS_DAYS = 3
_STALLED_AWAITING_APPROVAL_DAYS = 3
_DECLINING_AVERAGE_REPAIR_ORDER_THRESHOLD = 0.15
_MAX_INSIGHTS = 10


@dataclass(frozen=True)
class _InvoicePeriodAggregate:
    revenue: float
    labor: float
    parts: float
    fees: float
    count: int
    average: float | None


def _period_aggregate(
    db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> _InvoicePeriodAggregate:
    row = db.execute(
        select(
            func.coalesce(func.sum(Invoice.invoice_total), 0.0),
            func.coalesce(func.sum(Invoice.labor_total), 0.0),
            func.coalesce(func.sum(Invoice.parts_total), 0.0),
            func.coalesce(func.sum(Invoice.fees_total), 0.0),
            func.count(Invoice.id),
        ).where(
            Invoice.owner_user_id == effective_owner_id(auth),
            Invoice.status.in_([s.value for s in _ISSUED_INVOICE_STATUSES]),
            Invoice.issued_at.is_not(None),
            Invoice.issued_at >= date_from,
            Invoice.issued_at <= date_to,
        )
    ).one()
    revenue, labor, parts, fees, count = row
    average = (revenue / count) if count else None
    return _InvoicePeriodAggregate(
        revenue=float(revenue),
        labor=float(labor),
        parts=float(parts),
        fees=float(fees),
        count=int(count),
        average=average,
    )


def _period_cogs(
    db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> tuple[float, int]:
    """Approximate cost of parts consumed in the period, from Phase 6 Part
    F's real purchase-cost data: sums quantity x unit_cost_snapshot for every
    part_allocation_events row marked "used" with created_at in the window.

    This is a *usage-period* approximation, not accrual-matched to invoice
    revenue in the same window -- a part used on the last day of June but not
    invoiced until July counts its cost in June's Gross Profit and its
    revenue in July's. Accepted as directionally useful, not exact accrual
    accounting; see KNOWN_ISSUES.md.

    Parts used without a recorded `unit_cost_snapshot` (never received
    through a costed purchase order) are excluded from the cost sum rather
    than assigned a fabricated cost; their quantity is returned separately so
    the caller can disclose the gap instead of silently understating COGS."""
    cost_expr = func.coalesce(
        func.sum(
            case(
                (
                    PartAllocation.unit_cost_snapshot.is_not(None),
                    PartAllocationEvent.quantity_delta * PartAllocation.unit_cost_snapshot,
                ),
                else_=0,
            )
        ),
        0.0,
    )
    missing_cost_quantity_expr = func.coalesce(
        func.sum(
            case(
                (PartAllocation.unit_cost_snapshot.is_(None), PartAllocationEvent.quantity_delta),
                else_=0,
            )
        ),
        0,
    )
    row = db.execute(
        select(cost_expr, missing_cost_quantity_expr)
        .select_from(PartAllocationEvent)
        .join(PartAllocation, PartAllocation.id == PartAllocationEvent.allocation_id)
        .where(
            PartAllocation.owner_user_id == effective_owner_id(auth),
            PartAllocationEvent.event_type == "used",
            PartAllocationEvent.created_at >= date_from,
            PartAllocationEvent.created_at <= date_to,
        )
    ).one()
    cogs, missing_cost_quantity = row
    return float(cogs), int(missing_cost_quantity or 0)


def _change_percent(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 1)


def _month_key(value: datetime) -> tuple[int, int]:
    utc_value = ensure_utc(value)
    return utc_value.year, utc_value.month


def _month_label(year: int, month: int) -> str:
    return datetime(year, month, 1).strftime("%b %Y")


def _revenue_trend(
    db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> list[DashboardTrendPoint]:
    rows = db.execute(
        select(
            Invoice.issued_at,
            Invoice.invoice_total,
            Invoice.labor_total,
            Invoice.parts_total,
        ).where(
            Invoice.owner_user_id == effective_owner_id(auth),
            Invoice.status.in_([s.value for s in _ISSUED_INVOICE_STATUSES]),
            Invoice.issued_at.is_not(None),
            Invoice.issued_at >= date_from,
            Invoice.issued_at <= date_to,
        )
    ).all()

    buckets: dict[tuple[int, int], dict[str, float]] = defaultdict(
        lambda: {"revenue": 0.0, "labor": 0.0, "parts": 0.0}
    )
    for issued_at, invoice_total, labor_total, parts_total in rows:
        key = _month_key(issued_at)
        buckets[key]["revenue"] += float(invoice_total)
        buckets[key]["labor"] += float(labor_total)
        buckets[key]["parts"] += float(parts_total)

    return [
        DashboardTrendPoint(
            period_label=_month_label(year, month),
            period_start=datetime(year, month, 1),
            values=values,
        )
        for (year, month), values in sorted(buckets.items())
    ]


def _work_order_trend(
    db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> list[DashboardTrendPoint]:
    opened_rows = db.execute(
        select(WorkOrder.created_at).where(
            WorkOrder.owner_user_id == effective_owner_id(auth),
            WorkOrder.created_at >= date_from,
            WorkOrder.created_at <= date_to,
        )
    ).all()
    completed_rows = db.execute(
        select(WorkOrderStatusEvent.created_at)
        .join(WorkOrder, WorkOrder.id == WorkOrderStatusEvent.work_order_id)
        .where(
            WorkOrder.owner_user_id == effective_owner_id(auth),
            WorkOrderStatusEvent.to_status == WorkOrderStatus.COMPLETED.value,
            WorkOrderStatusEvent.created_at >= date_from,
            WorkOrderStatusEvent.created_at <= date_to,
        )
    ).all()

    buckets: dict[tuple[int, int], dict[str, float]] = defaultdict(
        lambda: {"opened": 0.0, "completed": 0.0}
    )
    for (created_at,) in opened_rows:
        buckets[_month_key(created_at)]["opened"] += 1
    for (created_at,) in completed_rows:
        buckets[_month_key(created_at)]["completed"] += 1

    return [
        DashboardTrendPoint(
            period_label=_month_label(year, month),
            period_start=datetime(year, month, 1),
            values=values,
        )
        for (year, month), values in sorted(buckets.items())
    ]


def _approval_conversion_rate(
    db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> DashboardMetric:
    row = db.execute(
        select(Estimate.status, func.count())
        .where(
            Estimate.owner_user_id == effective_owner_id(auth),
            Estimate.status.in_([EstimateStatus.APPROVED.value, EstimateStatus.DECLINED.value]),
            Estimate.updated_at >= date_from,
            Estimate.updated_at <= date_to,
        )
        .group_by(Estimate.status)
    ).all()
    counts = {status: count for status, count in row}
    approved = counts.get(EstimateStatus.APPROVED.value, 0)
    declined = counts.get(EstimateStatus.DECLINED.value, 0)
    decided = approved + declined
    if decided == 0:
        return DashboardMetric(
            key="approval_conversion_rate",
            label="Approval Conversion Rate",
            available=False,
            unavailable_reason="No estimates decided in the selected period.",
        )
    return DashboardMetric(
        key="approval_conversion_rate",
        label="Approval Conversion Rate",
        available=True,
        value=round((approved / decided) * 100, 1),
    )


def _accounts_receivable(
    db: Session, auth: AuthContext, now: datetime
) -> tuple[DashboardMetric, DashboardFinancialObligations]:
    open_invoices = list(
        db.scalars(
            select(Invoice)
            .options(selectinload(Invoice.payments), selectinload(Invoice.schedule))
            .where(
                Invoice.owner_user_id == effective_owner_id(auth),
                Invoice.status.in_([s.value for s in _OPEN_INVOICE_STATUSES]),
            )
        )
    )

    outstanding = 0.0
    overdue = 0.0
    overdue_count = 0
    deposits_total = 0.0
    for invoice in open_invoices:
        total_paid, _effective_status, is_overdue = _payment_summary(invoice, now=now)
        invoice_total = _money(invoice.invoice_total)
        balance_due = max(invoice_total - total_paid, 0)
        outstanding += float(balance_due)
        if is_overdue:
            overdue += float(balance_due)
            overdue_count += 1
        for payment in invoice.payments:
            if payment.applies_to == "deposit" and payment.amount > 0:
                deposits_total += float(_money(payment.amount))

    upcoming: list[DashboardUpcomingInstallment] = []
    for invoice in open_invoices:
        for entry in invoice.schedule:
            if entry.due_at is None or ensure_utc(entry.due_at) < now:
                continue
            upcoming.append(
                DashboardUpcomingInstallment(
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    label=entry.label,
                    amount=float(entry.amount),
                    due_at=entry.due_at,
                )
            )
    upcoming.sort(key=lambda item: item.due_at or now)
    upcoming = upcoming[:10]

    health_value = 100.0 if outstanding == 0 else round((1 - (overdue / outstanding)) * 100, 1)
    ar_metric = DashboardMetric(
        key="accounts_receivable_health",
        label="Accounts Receivable Health",
        available=True,
        value=health_value,
    )
    obligations = DashboardFinancialObligations(
        outstanding_balance=round(outstanding, 2),
        overdue_balance=round(overdue, 2),
        overdue_invoice_count=overdue_count,
        upcoming_installments=upcoming,
        deposits_received_total=round(deposits_total, 2),
    )
    return ar_metric, obligations


def _current_operations(db: Session, auth: AuthContext) -> DashboardCurrentOperations:
    rows = db.execute(
        select(WorkOrder.status, func.count())
        .where(WorkOrder.owner_user_id == effective_owner_id(auth))
        .group_by(WorkOrder.status)
    ).all()
    counts = {status: count for status, count in rows}
    non_open = {WorkOrderStatus.COMPLETED.value, WorkOrderStatus.CANCELLED.value}
    open_work_orders = sum(c for s, c in counts.items() if s not in non_open)
    in_progress = counts.get(WorkOrderStatus.IN_PROGRESS.value, 0)
    waiting_on_parts = counts.get(WorkOrderStatus.WAITING_FOR_PARTS.value, 0)

    awaiting_approval = (
        db.scalar(
            select(func.count())
            .select_from(Estimate)
            .where(
                Estimate.owner_user_id == effective_owner_id(auth),
                Estimate.status == EstimateStatus.AWAITING_APPROVAL.value,
            )
        )
        or 0
    )
    completed_not_invoiced = (
        db.scalar(
            select(func.count())
            .select_from(WorkOrder)
            .outerjoin(Invoice, Invoice.work_order_id == WorkOrder.id)
            .where(
                WorkOrder.owner_user_id == effective_owner_id(auth),
                WorkOrder.status == WorkOrderStatus.COMPLETED.value,
                Invoice.id.is_(None),
            )
        )
        or 0
    )

    return DashboardCurrentOperations(
        open_work_orders=int(open_work_orders),
        in_progress=int(in_progress),
        waiting_on_parts=int(waiting_on_parts),
        awaiting_customer_approval=int(awaiting_approval),
        completed_not_invoiced=int(completed_not_invoiced),
        ready_for_pickup_note=(
            "OptimusOS has no distinct 'ready for pickup' work-order status yet; "
            "Completed work orders not yet invoiced are shown above instead."
        ),
    )


def _work_orders_by_status(db: Session, auth: AuthContext) -> list[DashboardWorkOrderStatusCount]:
    rows = db.execute(
        select(WorkOrder.status, func.count())
        .where(WorkOrder.owner_user_id == effective_owner_id(auth))
        .group_by(WorkOrder.status)
    ).all()
    counts = {status: count for status, count in rows}
    return [
        DashboardWorkOrderStatusCount(status=status, count=int(counts.get(status.value, 0)))
        for status in WorkOrderStatus
    ]


def _stalled_work_order_insights(
    db: Session, auth: AuthContext, now: datetime
) -> list[DashboardInsight]:
    # Uses the actual status-transition timestamp (when the work order most
    # recently entered waiting_for_parts) rather than WorkOrder.updated_at,
    # since updated_at is also bumped by unrelated note additions and would
    # understate how long the job has actually been stalled.
    threshold = now - timedelta(days=_STALLED_WAITING_FOR_PARTS_DAYS)
    entered_at_subquery = (
        select(
            WorkOrderStatusEvent.work_order_id,
            func.max(WorkOrderStatusEvent.created_at).label("entered_at"),
        )
        .where(WorkOrderStatusEvent.to_status == WorkOrderStatus.WAITING_FOR_PARTS.value)
        .group_by(WorkOrderStatusEvent.work_order_id)
        .subquery()
    )
    rows = db.execute(
        select(WorkOrder, entered_at_subquery.c.entered_at)
        .join(entered_at_subquery, entered_at_subquery.c.work_order_id == WorkOrder.id)
        .where(
            WorkOrder.owner_user_id == effective_owner_id(auth),
            WorkOrder.status == WorkOrderStatus.WAITING_FOR_PARTS.value,
            entered_at_subquery.c.entered_at <= threshold,
        )
        .order_by(entered_at_subquery.c.entered_at)
        .limit(5)
    ).all()
    insights = []
    for work_order, entered_at in rows:
        days_waiting = (now - ensure_utc(entered_at)).days
        insights.append(
            DashboardInsight(
                key=f"waiting-for-parts-{work_order.id}",
                priority=DashboardInsightPriority.MEDIUM,
                issue=f"Work order {work_order.estimate_number} has waited on parts for {days_waiting} days.",
                metric=f"{days_waiting} days in waiting_for_parts",
                recommended_action="Check parts-order status or contact the vendor.",
                link_view="work-orders",
                link_record_id=work_order.id,
                generated_at=now,
            )
        )
    return insights


def _stalled_approval_insights(
    db: Session, auth: AuthContext, now: datetime
) -> list[DashboardInsight]:
    # Uses the most recent approval-request send time (when the customer
    # link was actually generated) rather than Estimate.updated_at, which
    # can be touched by unrelated edits and would understate wait time.
    threshold = now - timedelta(days=_STALLED_AWAITING_APPROVAL_DAYS)
    sent_at_subquery = (
        select(
            EstimateApprovalRequest.estimate_id,
            func.max(EstimateApprovalRequest.created_at).label("sent_at"),
        )
        .group_by(EstimateApprovalRequest.estimate_id)
        .subquery()
    )
    rows = db.execute(
        select(Estimate, sent_at_subquery.c.sent_at)
        .join(sent_at_subquery, sent_at_subquery.c.estimate_id == Estimate.id)
        .where(
            Estimate.owner_user_id == effective_owner_id(auth),
            Estimate.status == EstimateStatus.AWAITING_APPROVAL.value,
            sent_at_subquery.c.sent_at <= threshold,
        )
        .order_by(sent_at_subquery.c.sent_at)
        .limit(5)
    ).all()
    insights = []
    for estimate, sent_at in rows:
        days_waiting = (now - ensure_utc(sent_at)).days
        insights.append(
            DashboardInsight(
                key=f"awaiting-approval-{estimate.id}",
                priority=DashboardInsightPriority.MEDIUM,
                issue=f"Estimate {estimate.estimate_number} has awaited customer approval for {days_waiting} days.",
                metric=f"{days_waiting} days in awaiting_approval",
                recommended_action="Follow up with the customer before the approval link expires.",
                link_view="estimate",
                link_record_id=estimate.id,
                generated_at=now,
            )
        )
    return insights


def _overdue_invoice_insight(
    overdue_count: int, overdue_balance: float, now: datetime
) -> list[DashboardInsight]:
    if overdue_count == 0:
        return []
    return [
        DashboardInsight(
            key="overdue-invoices",
            priority=DashboardInsightPriority.HIGH,
            issue=f"{overdue_count} invoice(s) are overdue, totaling ${overdue_balance:,.2f}.",
            metric=f"${overdue_balance:,.2f} overdue across {overdue_count} invoice(s)",
            recommended_action="Follow up with customers on overdue balances.",
            link_view="invoices",
            generated_at=now,
        )
    ]


def _completed_not_invoiced_insight(count: int, now: datetime) -> list[DashboardInsight]:
    if count == 0:
        return []
    return [
        DashboardInsight(
            key="completed-not-invoiced",
            priority=DashboardInsightPriority.HIGH,
            issue=f"{count} work order(s) are completed but have not generated an invoice yet.",
            metric=f"{count} completed work order(s) without an invoice",
            recommended_action="Open each work order and confirm invoice generation.",
            link_view="work-orders",
            generated_at=now,
        )
    ]


def _declining_average_repair_order_insight(
    current: _InvoicePeriodAggregate, previous: _InvoicePeriodAggregate, now: datetime
) -> list[DashboardInsight]:
    if previous.average is None or current.average is None:
        return []
    if previous.average <= 0:
        return []
    change = (current.average - previous.average) / previous.average
    if change > -_DECLINING_AVERAGE_REPAIR_ORDER_THRESHOLD:
        return []
    return [
        DashboardInsight(
            key="declining-average-repair-order",
            priority=DashboardInsightPriority.LOW,
            issue=(
                f"Average repair order dropped {abs(change) * 100:.1f}% versus the prior period "
                f"(${previous.average:,.2f} -> ${current.average:,.2f})."
            ),
            metric=f"{abs(change) * 100:.1f}% decrease",
            recommended_action="Review recent estimates for scope, pricing, or upsell opportunities.",
            link_view="invoices",
            generated_at=now,
        )
    ]


def _missing_part_cost_insight(missing_cost_quantity: int, now: datetime) -> list[DashboardInsight]:
    if missing_cost_quantity <= 0:
        return []
    return [
        DashboardInsight(
            key="parts-missing-cost-data",
            priority=DashboardInsightPriority.LOW,
            issue=(
                f"{missing_cost_quantity} part unit(s) used this period have no recorded "
                "purchase cost, so Gross Profit is understated by that amount."
            ),
            metric=f"{missing_cost_quantity} unit(s) missing cost",
            recommended_action=(
                "Receive those parts through a Purchase Order so their cost is recorded, "
                "or set a unit cost directly on the Part record."
            ),
            link_view="parts",
            generated_at=now,
        )
    ]


def get_dashboard_summary(
    *,
    db: Session,
    auth: AuthContext,
    date_from: datetime,
    date_to: datetime,
) -> DashboardSummaryResponse:
    now = now_utc()
    period_length = date_to - date_from
    previous_from = date_from - period_length
    previous_to = date_from

    current = _period_aggregate(db, auth, date_from, date_to)
    previous = _period_aggregate(db, auth, previous_from, previous_to)
    current_cogs, current_missing_cost_quantity = _period_cogs(db, auth, date_from, date_to)
    previous_cogs, _ = _period_cogs(db, auth, previous_from, previous_to)
    current_gross_profit = current.revenue - current_cogs
    previous_gross_profit = previous.revenue - previous_cogs

    def metric(
        key: str, label: str, current_value: float, previous_value: float | None
    ) -> DashboardMetric:
        return DashboardMetric(
            key=key,
            label=label,
            available=True,
            value=round(current_value, 2),
            previous_value=round(previous_value, 2) if previous_value is not None else None,
            change_percent=_change_percent(current_value, previous_value),
        )

    operations = _current_operations(db, auth)
    ar_metric, obligations = _accounts_receivable(db, auth, now)
    approval_conversion = _approval_conversion_rate(db, auth, date_from, date_to)

    metrics = [
        metric("revenue", "Revenue", current.revenue, previous.revenue),
        metric("labor_revenue", "Labor Revenue", current.labor, previous.labor),
        metric("parts_revenue", "Parts Revenue", current.parts, previous.parts),
        DashboardMetric(
            key="average_repair_order",
            label="Average Repair Order",
            available=current.average is not None,
            value=round(current.average, 2) if current.average is not None else None,
            previous_value=round(previous.average, 2) if previous.average is not None else None,
            change_percent=_change_percent(current.average, previous.average),
            unavailable_reason=(
                None
                if current.average is not None
                else "No issued invoices in the selected period."
            ),
        ),
        DashboardMetric(
            key="open_work_orders",
            label="Open Work Orders",
            available=True,
            value=float(operations.open_work_orders),
        ),
        DashboardMetric(
            key="awaiting_customer_approval",
            label="Awaiting Customer Approval",
            available=True,
            value=float(operations.awaiting_customer_approval),
        ),
        metric("gross_profit", "Gross Profit", current_gross_profit, previous_gross_profit),
        DashboardMetric(
            key="net_profit",
            label="Net Profit",
            available=False,
            unavailable_reason="Connect expense tracking to display this metric.",
        ),
    ]

    revenue_total = current.labor + current.parts + current.fees
    revenue_breakdown = (
        [
            DashboardRevenueBreakdownItem(
                label="Labor",
                amount=round(current.labor, 2),
                percent=round((current.labor / revenue_total) * 100, 1),
            ),
            DashboardRevenueBreakdownItem(
                label="Parts",
                amount=round(current.parts, 2),
                percent=round((current.parts / revenue_total) * 100, 1),
            ),
            DashboardRevenueBreakdownItem(
                label="Fees",
                amount=round(current.fees, 2),
                percent=round((current.fees / revenue_total) * 100, 1),
            ),
        ]
        if revenue_total > 0
        else []
    )

    gross_profit_margin = (
        DashboardMetric(
            key="gross_profit_margin",
            label="Gross Profit Margin",
            available=True,
            value=round((current_gross_profit / current.revenue) * 100, 1),
            previous_value=(
                round((previous_gross_profit / previous.revenue) * 100, 1)
                if previous.revenue > 0
                else None
            ),
        )
        if current.revenue > 0
        else DashboardMetric(
            key="gross_profit_margin",
            label="Gross Profit Margin",
            available=False,
            unavailable_reason="No revenue in the selected period.",
        )
    )

    insights = (
        _overdue_invoice_insight(
            obligations.overdue_invoice_count, obligations.overdue_balance, now
        )
        + _completed_not_invoiced_insight(operations.completed_not_invoiced, now)
        + _stalled_work_order_insights(db, auth, now)
        + _stalled_approval_insights(db, auth, now)
        + _declining_average_repair_order_insight(current, previous, now)
        + _missing_part_cost_insight(current_missing_cost_quantity, now)
    )
    priority_order = {
        DashboardInsightPriority.HIGH: 0,
        DashboardInsightPriority.MEDIUM: 1,
        DashboardInsightPriority.LOW: 2,
    }
    insights.sort(key=lambda insight: priority_order[insight.priority])
    insights = insights[:_MAX_INSIGHTS]

    return DashboardSummaryResponse(
        date_from=date_from,
        date_to=date_to,
        metrics=metrics,
        revenue_trend=_revenue_trend(db, auth, date_from, date_to),
        work_order_trend=_work_order_trend(db, auth, date_from, date_to),
        revenue_breakdown=revenue_breakdown,
        gross_profit_margin=gross_profit_margin,
        approval_conversion_rate=approval_conversion,
        accounts_receivable_health=ar_metric,
        work_orders_by_status=_work_orders_by_status(db, auth),
        current_operations=operations,
        financial_obligations=obligations,
        insights=insights,
    )
