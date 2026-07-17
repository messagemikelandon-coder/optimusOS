from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id, ensure_utc
from app.db_models import (
    DiagnosticFinding,
    Inspection,
    Invoice,
    InvoicePayment,
    Part,
    PartAllocation,
    PartAllocationEvent,
    PurchaseOrder,
    Technician,
    TechnicianTimeEntry,
    Vendor,
    WorkOrder,
    WorkOrderStatusEvent,
)
from app.models import (
    DashboardMetric,
    DiagnosticInspectionReportResponse,
    InspectionItem,
    InventoryValuationReportResponse,
    LowStockPartRead,
    PartsUsageReportResponse,
    PartUsageEntryRead,
    PaymentActivityBreakdownItem,
    PaymentActivityEntryRead,
    PaymentActivityReportResponse,
    PaymentAppliesTo,
    PurchaseOrderStatus,
    TechnicianTimeReportResponse,
    TechnicianTimeSummaryRead,
    VendorPurchasingBreakdownItem,
    VendorPurchasingReportResponse,
    WorkOrderCycleTimeReportResponse,
    WorkOrderStatus,
)
from app.technician_store import display_name as technician_display_name

__all__ = [
    "get_diagnostic_inspection_report",
    "get_inventory_valuation_report",
    "get_parts_usage_report",
    "get_payment_activity_report",
    "get_technician_time_report",
    "get_vendor_purchasing_report",
    "get_work_order_cycle_time_report",
]


def get_payment_activity_report(
    *, db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> PaymentActivityReportResponse:
    rows = db.execute(
        select(InvoicePayment, Invoice.invoice_number)
        .join(Invoice, Invoice.id == InvoicePayment.invoice_id)
        .where(
            InvoicePayment.owner_user_id == effective_owner_id(auth),
            InvoicePayment.recorded_at >= date_from,
            InvoicePayment.recorded_at < date_to,
        )
        .order_by(InvoicePayment.recorded_at.desc())
    ).all()

    entries: list[PaymentActivityEntryRead] = []
    total_collected = Decimal("0")
    by_method: dict[str, tuple[Decimal, int]] = defaultdict(lambda: (Decimal("0"), 0))
    by_applies_to: dict[str, tuple[Decimal, int]] = defaultdict(lambda: (Decimal("0"), 0))

    for payment, invoice_number in rows:
        entries.append(
            PaymentActivityEntryRead(
                id=payment.id,
                invoice_id=payment.invoice_id,
                invoice_number=invoice_number,
                amount=float(payment.amount),
                applies_to=PaymentAppliesTo(payment.applies_to),
                method_label=payment.method_label,
                recorded_at=ensure_utc(payment.recorded_at),
                is_reversal=payment.reversal_of_payment_id is not None,
            )
        )
        # Reversal rows are stored with a negative amount (enforced by the
        # ck_invoice_payments_amount_sign CHECK constraint), so summing raw
        # amounts here correctly nets a voided payment back out rather than
        # double-counting it as still-collected revenue.
        total_collected += payment.amount
        method_total, method_count = by_method[payment.method_label]
        by_method[payment.method_label] = (method_total + payment.amount, method_count + 1)
        applies_total, applies_count = by_applies_to[payment.applies_to]
        by_applies_to[payment.applies_to] = (applies_total + payment.amount, applies_count + 1)

    return PaymentActivityReportResponse(
        date_from=ensure_utc(date_from),
        date_to=ensure_utc(date_to),
        entries=entries,
        total_collected=float(total_collected),
        payment_count=len(entries),
        by_method=[
            PaymentActivityBreakdownItem(label=label, total=float(total), count=count)
            for label, (total, count) in sorted(by_method.items())
        ],
        by_applies_to=[
            PaymentActivityBreakdownItem(label=label, total=float(total), count=count)
            for label, (total, count) in sorted(by_applies_to.items())
        ],
    )


def get_technician_time_report(
    *, db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> TechnicianTimeReportResponse:
    technicians = db.scalars(
        select(Technician).where(
            Technician.owner_user_id == effective_owner_id(auth),
            Technician.is_archived.is_(False),
        )
    ).all()

    summaries: list[TechnicianTimeSummaryRead] = []
    total_hours = 0.0
    total_cost = Decimal("0")
    technicians_missing_hourly_cost = 0

    for technician in technicians:
        # Filtered on clock_in_at, not on any clock_in/clock_out overlap with
        # the window: a shift that started before date_from and ended inside
        # the window is excluded entirely, so none of its in-window hours are
        # counted. Accepted for now since shifts rarely span a reporting
        # boundary in this shop's usage; revisit with an overlap filter if
        # that assumption stops holding. See KNOWN_ISSUES.md.
        entries = db.scalars(
            select(TechnicianTimeEntry).where(
                TechnicianTimeEntry.technician_id == technician.id,
                TechnicianTimeEntry.clock_in_at >= date_from,
                TechnicianTimeEntry.clock_in_at < date_to,
            )
        ).all()
        closed_durations = [
            entry.clock_out_at - entry.clock_in_at
            for entry in entries
            if entry.clock_out_at is not None
        ]
        open_entry_count = len(entries) - len(closed_durations)
        hours = sum(duration.total_seconds() / 3600 for duration in closed_durations)
        if hours == 0 and open_entry_count == 0:
            # No activity for this technician in the period -- omit rather
            # than clutter the report with an all-zero row.
            continue

        labor_cost: float | None = None
        if technician.hourly_cost is not None:
            labor_cost_decimal = technician.hourly_cost * Decimal(str(round(hours, 4)))
            labor_cost = float(labor_cost_decimal)
            total_cost += labor_cost_decimal
        elif hours > 0:
            technicians_missing_hourly_cost += 1

        summaries.append(
            TechnicianTimeSummaryRead(
                technician_id=technician.id,
                technician_display_name=technician_display_name(technician),
                clocked_hours=round(hours, 2),
                labor_cost=round(labor_cost, 2) if labor_cost is not None else None,
                open_entry_count=open_entry_count,
            )
        )
        total_hours += hours

    return TechnicianTimeReportResponse(
        date_from=ensure_utc(date_from),
        date_to=ensure_utc(date_to),
        technicians=summaries,
        total_clocked_hours=round(total_hours, 2),
        total_labor_cost=round(float(total_cost), 2),
        technicians_missing_hourly_cost=technicians_missing_hourly_cost,
        billed_hours=DashboardMetric(
            key="technician_billed_hours",
            label="Billed hours (vs. clocked)",
            available=False,
            unavailable_reason=(
                "Time entries aren't linked to a specific work order yet, so a "
                "billed-vs-clocked comparison isn't available. This report shows "
                "clocked hours and labor cost only."
            ),
        ),
        commission=DashboardMetric(
            key="technician_commission",
            label="Commission",
            available=False,
            unavailable_reason=(
                "OptimusOS doesn't track a commission rate per technician, only an "
                "hourly cost. This report shows labor cost (hourly cost x clocked "
                "hours) instead of commission."
            ),
        ),
    )


def get_inventory_valuation_report(
    *, db: Session, auth: AuthContext
) -> InventoryValuationReportResponse:
    parts = db.execute(
        select(Part, Vendor.name)
        .outerjoin(Vendor, Vendor.id == Part.vendor_id)
        .where(
            Part.owner_user_id == effective_owner_id(auth),
            Part.is_archived.is_(False),
        )
    ).all()

    total_valuation = Decimal("0")
    total_units_on_hand = 0
    parts_missing_cost_count = 0
    low_stock_parts: list[LowStockPartRead] = []

    for part, vendor_name in parts:
        total_units_on_hand += part.quantity_on_hand
        if part.unit_cost is not None:
            total_valuation += part.unit_cost * part.quantity_on_hand
        elif part.quantity_on_hand > 0:
            # Uncosted parts are excluded from the dollar total rather than
            # assigned a fabricated cost; counted separately so the gap is
            # disclosed instead of silently understating the valuation.
            parts_missing_cost_count += 1

        if part.reorder_threshold is not None and part.quantity_on_hand <= part.reorder_threshold:
            low_stock_parts.append(
                LowStockPartRead(
                    part_id=part.id,
                    part_number=part.part_number,
                    description=part.description,
                    quantity_on_hand=part.quantity_on_hand,
                    reorder_threshold=part.reorder_threshold,
                    vendor_display_name=vendor_name,
                )
            )

    low_stock_parts.sort(key=lambda p: p.quantity_on_hand - p.reorder_threshold)

    return InventoryValuationReportResponse(
        total_valuation=float(total_valuation),
        total_units_on_hand=total_units_on_hand,
        parts_counted=len(parts),
        parts_missing_cost_count=parts_missing_cost_count,
        low_stock_parts=low_stock_parts,
    )


def get_parts_usage_report(
    *, db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> PartsUsageReportResponse:
    """Per-part breakdown of the same "used" `PartAllocationEvent` data source
    that feeds the dashboard's Gross Profit COGS figure -- see
    `dashboard_store.py::_period_cogs` for the shared usage-period-approximation
    caveat (documented in `KNOWN_ISSUES.md`). The totals won't always tie out
    to the penny with `_period_cogs`, though: this function uses this file's
    `date_to` convention (exclusive, `<`, matching every other report here)
    rather than `_period_cogs`'s inclusive `<=`, so an event landing exactly
    on `date_to` can appear in one and not the other. Usage with no recorded
    `unit_cost_snapshot` is excluded from `cost_total` rather than assigned a
    fabricated cost, and counted separately in `quantity_missing_cost`."""
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
    missing_cost_expr = func.coalesce(
        func.sum(
            case(
                (PartAllocation.unit_cost_snapshot.is_(None), PartAllocationEvent.quantity_delta),
                else_=0,
            )
        ),
        0,
    )
    quantity_expr = func.coalesce(func.sum(PartAllocationEvent.quantity_delta), 0)

    rows = db.execute(
        select(
            Part.id,
            Part.part_number,
            Part.description,
            quantity_expr,
            cost_expr,
            missing_cost_expr,
        )
        .select_from(PartAllocationEvent)
        .join(PartAllocation, PartAllocation.id == PartAllocationEvent.allocation_id)
        .join(Part, Part.id == PartAllocation.part_id)
        .where(
            PartAllocation.owner_user_id == effective_owner_id(auth),
            PartAllocationEvent.event_type == "used",
            PartAllocationEvent.created_at >= date_from,
            PartAllocationEvent.created_at < date_to,
        )
        .group_by(Part.id, Part.part_number, Part.description)
    ).all()

    parts: list[PartUsageEntryRead] = []
    total_quantity_used = 0
    total_cost = Decimal("0")
    total_quantity_missing_cost = 0
    for part_id, part_number, description, quantity, cost, missing_cost in rows:
        cost_decimal = Decimal(str(cost))
        parts.append(
            PartUsageEntryRead(
                part_id=part_id,
                part_number=part_number,
                description=description,
                quantity_used=int(quantity),
                cost_total=float(cost_decimal),
                quantity_missing_cost=int(missing_cost),
            )
        )
        total_quantity_used += int(quantity)
        total_cost += cost_decimal
        total_quantity_missing_cost += int(missing_cost)

    # Most-used parts first -- the actionable ordering for a shop owner
    # scanning this report to see which parts to keep well-stocked.
    parts.sort(key=lambda p: p.quantity_used, reverse=True)

    return PartsUsageReportResponse(
        date_from=ensure_utc(date_from),
        date_to=ensure_utc(date_to),
        parts=parts,
        total_quantity_used=total_quantity_used,
        total_cost=float(total_cost),
        total_quantity_missing_cost=total_quantity_missing_cost,
    )


def get_vendor_purchasing_report(
    *, db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> VendorPurchasingReportResponse:
    """Only purchase orders that were actually submitted (`submitted_at` in
    the window) count as spend -- a `draft` PO is never a real commitment.
    Submitted-then-cancelled orders are excluded from spend and counted
    separately in `cancelled_order_count` rather than counted as spend that
    never actually happened.

    Known imprecision: a PO can be cancelled from `partially_received` (see
    `purchase_order_store.py`'s status transitions), meaning some of its
    parts were genuinely received -- and paid for -- before the rest was
    cancelled. This report still excludes the *entire* order's total from
    spend in that case, since `PurchaseOrder.total` is fixed at creation time
    and isn't reduced by partial receiving, so there's no reliable
    already-spent subtotal to report instead. A fully `received` order can
    never be cancelled afterward (RECEIVED is terminal), so this gap is
    narrower than it sounds -- only reachable via partial receiving followed
    by cancellation -- and the disclosed `cancelled_order_count` at least
    surfaces that something was excluded, rather than hiding it silently."""
    rows = db.execute(
        select(
            PurchaseOrder.vendor_id,
            Vendor.name,
            PurchaseOrder.status,
            PurchaseOrder.total,
        )
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(
            PurchaseOrder.owner_user_id == effective_owner_id(auth),
            PurchaseOrder.submitted_at.is_not(None),
            PurchaseOrder.submitted_at >= date_from,
            PurchaseOrder.submitted_at < date_to,
        )
    ).all()

    by_vendor: dict[int, tuple[str, Decimal, int]] = {}
    total_spend = Decimal("0")
    total_orders = 0
    cancelled_order_count = 0

    for vendor_id, vendor_name, status, total in rows:
        if status == PurchaseOrderStatus.CANCELLED.value:
            cancelled_order_count += 1
            continue
        total_orders += 1
        total_spend += total
        name, spend, count = by_vendor.get(vendor_id, (vendor_name, Decimal("0"), 0))
        by_vendor[vendor_id] = (name, spend + total, count + 1)

    breakdown = [
        VendorPurchasingBreakdownItem(
            vendor_id=vendor_id, vendor_name=name, order_count=count, total_spend=float(spend)
        )
        for vendor_id, (name, spend, count) in by_vendor.items()
    ]
    breakdown.sort(key=lambda item: item.total_spend, reverse=True)

    return VendorPurchasingReportResponse(
        date_from=ensure_utc(date_from),
        date_to=ensure_utc(date_to),
        by_vendor=breakdown,
        total_spend=float(total_spend),
        total_orders=total_orders,
        cancelled_order_count=cancelled_order_count,
    )


def get_work_order_cycle_time_report(
    *, db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> WorkOrderCycleTimeReportResponse:
    """`completed` is a terminal `WorkOrder` status (no transition leads out
    of it), so each work order has at most one `to_status='completed'`
    status event -- the join below can't fan out or double-count a work
    order's cycle time."""
    rows = db.execute(
        select(WorkOrder.created_at, WorkOrder.is_comeback, WorkOrderStatusEvent.created_at)
        .join(WorkOrderStatusEvent, WorkOrderStatusEvent.work_order_id == WorkOrder.id)
        .where(
            WorkOrderStatusEvent.owner_user_id == effective_owner_id(auth),
            WorkOrderStatusEvent.to_status == WorkOrderStatus.COMPLETED.value,
            WorkOrderStatusEvent.created_at >= date_from,
            WorkOrderStatusEvent.created_at < date_to,
        )
    ).all()

    durations_hours = sorted(
        (completed_at - created_at).total_seconds() / 3600
        for created_at, _is_comeback, completed_at in rows
    )
    comeback_count = sum(1 for _created_at, is_comeback, _completed_at in rows if is_comeback)
    count = len(rows)

    if count == 0:
        average = median = fastest = slowest = 0.0
    else:
        average = sum(durations_hours) / count
        fastest = durations_hours[0]
        slowest = durations_hours[-1]
        midpoint = count // 2
        median = (
            durations_hours[midpoint]
            if count % 2 == 1
            else (durations_hours[midpoint - 1] + durations_hours[midpoint]) / 2
        )

    return WorkOrderCycleTimeReportResponse(
        date_from=ensure_utc(date_from),
        date_to=ensure_utc(date_to),
        completed_work_order_count=count,
        average_cycle_time_hours=round(average, 2),
        median_cycle_time_hours=round(median, 2),
        fastest_cycle_time_hours=round(fastest, 2),
        slowest_cycle_time_hours=round(slowest, 2),
        comeback_count=comeback_count,
        comeback_rate_percent=round((comeback_count / count * 100) if count else 0.0, 1),
    )


def get_diagnostic_inspection_report(
    *, db: Session, auth: AuthContext, date_from: datetime, date_to: datetime
) -> DiagnosticInspectionReportResponse:
    """Counts findings/inspections created in the window regardless of
    current `is_archived` status -- a deliberate choice, since this is an
    activity report (what work was logged in the period), and archiving
    afterward doesn't undo that the observation was made. Inspection `items`
    is stored as an untyped JSON column at the DB level, but the application
    layer (`InspectionItem` in `app/models.py`) enforces its shape on every
    write, so counting status literals in Python here is reading a genuinely
    structured field, not guessing at freeform data."""
    owner_id = effective_owner_id(auth)

    finding_rows = db.execute(
        select(DiagnosticFinding.conclusion).where(
            DiagnosticFinding.owner_user_id == owner_id,
            DiagnosticFinding.created_at >= date_from,
            DiagnosticFinding.created_at < date_to,
        )
    ).all()
    diagnostic_finding_count = len(finding_rows)
    findings_missing_conclusion = sum(1 for (conclusion,) in finding_rows if not conclusion)

    inspection_rows = db.execute(
        select(Inspection.items).where(
            Inspection.owner_user_id == owner_id,
            Inspection.created_at >= date_from,
            Inspection.created_at < date_to,
        )
    ).all()
    inspection_count = len(inspection_rows)
    inspection_item_count = 0
    items_ok = 0
    items_attention = 0
    items_fail = 0
    for (items,) in inspection_rows:
        for item in items or []:
            inspection_item_count += 1
            # Revalidate through the Pydantic model rather than reading the
            # raw dict directly -- matches inspection_store.py's own pattern
            # and means a malformed/corrupted status value raises loudly
            # instead of being silently counted as "ok".
            status = InspectionItem.model_validate(item).status
            if status == "attention":
                items_attention += 1
            elif status == "fail":
                items_fail += 1
            else:
                items_ok += 1

    return DiagnosticInspectionReportResponse(
        date_from=ensure_utc(date_from),
        date_to=ensure_utc(date_to),
        diagnostic_finding_count=diagnostic_finding_count,
        findings_missing_conclusion=findings_missing_conclusion,
        inspection_count=inspection_count,
        inspection_item_count=inspection_item_count,
        items_ok=items_ok,
        items_attention=items_attention,
        items_fail=items_fail,
    )
