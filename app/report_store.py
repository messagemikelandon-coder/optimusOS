from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id, ensure_utc
from app.db_models import Invoice, InvoicePayment, Technician, TechnicianTimeEntry
from app.models import (
    DashboardMetric,
    PaymentActivityBreakdownItem,
    PaymentActivityEntryRead,
    PaymentActivityReportResponse,
    PaymentAppliesTo,
    TechnicianTimeReportResponse,
    TechnicianTimeSummaryRead,
)
from app.technician_store import display_name as technician_display_name

__all__ = ["get_payment_activity_report", "get_technician_time_report"]


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
