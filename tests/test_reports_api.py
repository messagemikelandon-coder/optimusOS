from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.auth import effective_owner_id
from app.db_models import TechnicianTimeEntry, WorkOrder, WorkOrderStatusEvent
from app.models import (
    DiagnosticFindingCreate,
    InspectionCreate,
    InspectionItem,
    InvoicePaymentCreate,
    InvoicePaymentVoidRequest,
    PaymentAppliesTo,
    PurchaseOrderCreate,
    PurchaseOrderLineItemCreate,
    PurchaseOrderReceiveRequest,
    WorkOrderUpdate,
)
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_dashboard_api import _use_part
from tests.test_diagnostics_and_inspections_api import _create_vehicle
from tests.test_payments_api import create_completed_work_order_with_invoice, issue
from tests.test_technicians_api import technician_payload
from tests.test_vendors_and_parts_api import part_payload, vendor_payload

pytestmark = pytest.mark.anyio


def _add_time_entry(
    db_session: Session,
    *,
    owner_user_id: int,
    technician_id: int,
    clock_in_at: datetime,
    clock_out_at: datetime | None,
) -> TechnicianTimeEntry:
    entry = TechnicianTimeEntry(
        technician_id=technician_id,
        owner_user_id=owner_user_id,
        clock_in_at=clock_in_at,
        clock_out_at=clock_out_at,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


# ---- Payment activity report ----


async def test_payment_activity_report_nets_reversals_and_breaks_down_by_method(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth)

    after_first = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(amount=40.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER),
        db_session,
        auth,
    )
    first_payment_id = after_first.payments[0].id
    await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(
            amount=25.0, method_label="card", applies_to=PaymentAppliesTo.INSTALLMENT
        ),
        db_session,
        auth,
    )
    await main.void_invoice_payment(
        issued.id,
        first_payment_id,
        InvoicePaymentVoidRequest(reason="Recorded in error"),
        db_session,
        auth,
    )

    report = await main.get_payment_activity_report_record(db_session, auth, None, None)

    assert report.payment_count == 3
    assert report.total_collected == pytest.approx(25.0)

    by_method = {item.label: (item.total, item.count) for item in report.by_method}
    assert by_method["cash"][0] == pytest.approx(0.0)
    assert by_method["cash"][1] == 2
    assert by_method["card"][0] == pytest.approx(25.0)
    assert by_method["card"][1] == 1

    by_applies_to = {item.label: (item.total, item.count) for item in report.by_applies_to}
    assert by_applies_to["other"][0] == pytest.approx(0.0)
    assert by_applies_to["other"][1] == 2
    assert by_applies_to["installment"][0] == pytest.approx(25.0)
    assert by_applies_to["installment"][1] == 1

    reversal_entries = [e for e in report.entries if e.is_reversal]
    assert len(reversal_entries) == 1
    assert reversal_entries[0].amount == pytest.approx(-40.0)
    assert reversal_entries[0].invoice_number == issued.invoice_number


async def test_payment_activity_report_date_range_excludes_out_of_window_payments(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    issued = await issue(invoice.id, db_session, settings, auth)
    await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(amount=10.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER),
        db_session,
        auth,
    )

    now = datetime.now(UTC)
    report = await main.get_payment_activity_report_record(
        db_session, auth, now - timedelta(days=10), now - timedelta(days=5)
    )

    assert report.payment_count == 0
    assert report.total_collected == 0.0
    assert report.by_method == []
    assert report.by_applies_to == []


async def test_payment_activity_report_invalid_date_range_rejected(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    now = datetime.now(UTC)
    with pytest.raises(HTTPException) as excinfo:
        await main.get_payment_activity_report_record(
            db_session, auth, now, now - timedelta(days=1)
        )
    assert excinfo.value.status_code == 422


async def test_payment_activity_report_cross_user_isolation(
    monkeypatch, settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(db_session, username="reports-isolation-other", password="other-password-123")
    _, other_response = await login_as(
        settings, db_session, username="reports-isolation-other", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, owner_auth
    )
    issued = await issue(invoice.id, db_session, settings, owner_auth)
    await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(amount=10.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER),
        db_session,
        owner_auth,
    )

    other_report = await main.get_payment_activity_report_record(db_session, other_auth, None, None)
    assert other_report.payment_count == 0
    assert other_report.total_collected == 0.0


# ---- Technician time report ----


async def test_technician_time_report_computes_hours_and_labor_cost(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    technician = await main.create_technician_record(
        technician_payload(hourly_cost=20.0), db_session, auth
    )

    now = datetime.now(UTC)
    _add_time_entry(
        db_session,
        owner_user_id=effective_owner_id(auth),
        technician_id=technician.id,
        clock_in_at=now - timedelta(hours=5),
        clock_out_at=now - timedelta(hours=3),
    )
    _add_time_entry(
        db_session,
        owner_user_id=effective_owner_id(auth),
        technician_id=technician.id,
        clock_in_at=now - timedelta(hours=2),
        clock_out_at=now - timedelta(hours=1, minutes=30),
    )
    _add_time_entry(
        db_session,
        owner_user_id=effective_owner_id(auth),
        technician_id=technician.id,
        clock_in_at=now - timedelta(minutes=20),
        clock_out_at=None,
    )

    report = await main.get_technician_time_report_record(db_session, auth, None, None)

    assert len(report.technicians) == 1
    summary = report.technicians[0]
    assert summary.technician_id == technician.id
    assert summary.clocked_hours == pytest.approx(2.5)
    assert summary.labor_cost == pytest.approx(50.0)
    assert summary.open_entry_count == 1

    assert report.total_clocked_hours == pytest.approx(2.5)
    assert report.total_labor_cost == pytest.approx(50.0)
    assert report.technicians_missing_hourly_cost == 0
    assert report.billed_hours.available is False
    assert report.commission.available is False


async def test_technician_time_report_flags_missing_hourly_cost(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    technician = await main.create_technician_record(
        technician_payload(hourly_cost=None), db_session, auth
    )

    now = datetime.now(UTC)
    _add_time_entry(
        db_session,
        owner_user_id=effective_owner_id(auth),
        technician_id=technician.id,
        clock_in_at=now - timedelta(hours=1),
        clock_out_at=now,
    )

    report = await main.get_technician_time_report_record(db_session, auth, None, None)

    assert len(report.technicians) == 1
    summary = report.technicians[0]
    assert summary.labor_cost is None
    assert report.technicians_missing_hourly_cost == 1
    assert report.total_labor_cost == 0.0


async def test_technician_time_report_excludes_archived_technicians(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    technician = await main.create_technician_record(
        technician_payload(hourly_cost=15.0), db_session, auth
    )
    now = datetime.now(UTC)
    _add_time_entry(
        db_session,
        owner_user_id=effective_owner_id(auth),
        technician_id=technician.id,
        clock_in_at=now - timedelta(hours=1),
        clock_out_at=now,
    )
    await main.archive_technician_record(technician.id, db_session, auth)

    report = await main.get_technician_time_report_record(db_session, auth, None, None)

    assert report.technicians == []
    assert report.total_clocked_hours == 0.0


async def test_technician_time_report_date_range_excludes_out_of_window_entries(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    technician = await main.create_technician_record(
        technician_payload(hourly_cost=15.0), db_session, auth
    )
    now = datetime.now(UTC)
    _add_time_entry(
        db_session,
        owner_user_id=effective_owner_id(auth),
        technician_id=technician.id,
        clock_in_at=now - timedelta(days=40),
        clock_out_at=now - timedelta(days=40) + timedelta(hours=1),
    )

    report = await main.get_technician_time_report_record(db_session, auth, None, None)

    assert report.technicians == []
    assert report.total_clocked_hours == 0.0


async def test_technician_time_report_shift_spanning_window_start_is_excluded(
    settings, db_session: Session
) -> None:
    """Documents a known, accepted limitation (see the comment in
    `report_store.get_technician_time_report` and `KNOWN_ISSUES.md`): the
    report filters on `clock_in_at`, not on any clock-in/clock-out overlap
    with the window, so a shift that started before `date_from` and ended
    inside the window has none of its in-window hours counted -- not just the
    portion before the window, but all of it. This test exists to make that
    behavior explicit and catch any accidental change to it, not to assert
    it's the ideal behavior."""
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    technician = await main.create_technician_record(
        technician_payload(hourly_cost=15.0), db_session, auth
    )
    window_start = datetime.now(UTC) - timedelta(days=1)
    _add_time_entry(
        db_session,
        owner_user_id=effective_owner_id(auth),
        technician_id=technician.id,
        clock_in_at=window_start - timedelta(hours=1),
        clock_out_at=window_start + timedelta(hours=2),
    )

    report = await main.get_technician_time_report_record(
        db_session, auth, window_start, window_start + timedelta(days=2)
    )

    assert report.technicians == []
    assert report.total_clocked_hours == 0.0


async def test_technician_time_report_invalid_date_range_rejected(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    now = datetime.now(UTC)
    with pytest.raises(HTTPException) as excinfo:
        await main.get_technician_time_report_record(db_session, auth, now, now - timedelta(days=1))
    assert excinfo.value.status_code == 422


async def test_technician_time_report_cross_user_isolation(settings, db_session: Session) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(db_session, username="tech-time-isolation-other", password="other-password-123")
    _, other_response = await login_as(
        settings, db_session, username="tech-time-isolation-other", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    technician = await main.create_technician_record(
        technician_payload(hourly_cost=15.0), db_session, owner_auth
    )
    now = datetime.now(UTC)
    _add_time_entry(
        db_session,
        owner_user_id=effective_owner_id(owner_auth),
        technician_id=technician.id,
        clock_in_at=now - timedelta(hours=1),
        clock_out_at=now,
    )

    other_report = await main.get_technician_time_report_record(db_session, other_auth, None, None)
    assert other_report.technicians == []
    assert other_report.total_clocked_hours == 0.0


# ---- Inventory valuation report ----


async def test_inventory_valuation_report_sums_costed_parts(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor = await main.create_vendor_record(vendor_payload(), db_session, auth)
    await main.create_part_record(
        part_payload(part_number="BP-1", quantity_on_hand=4, unit_cost=22.50, vendor_id=vendor.id),
        db_session,
        auth,
    )
    await main.create_part_record(
        part_payload(part_number="BP-2", quantity_on_hand=3, unit_cost=10.00, vendor_id=None),
        db_session,
        auth,
    )

    report = await main.get_inventory_valuation_report_record(db_session, auth)

    assert report.total_valuation == pytest.approx(4 * 22.50 + 3 * 10.00)
    assert report.total_units_on_hand == 7
    assert report.parts_counted == 2
    assert report.parts_missing_cost_count == 0


async def test_inventory_valuation_report_flags_missing_unit_cost(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    await main.create_part_record(
        part_payload(part_number="BP-3", quantity_on_hand=5, unit_cost=None),
        db_session,
        auth,
    )
    # A zero-stock part with no cost shouldn't be counted as "missing cost
    # data" -- there's nothing to disclose a gap about when there's no stock.
    await main.create_part_record(
        part_payload(part_number="BP-4", quantity_on_hand=0, unit_cost=None),
        db_session,
        auth,
    )

    report = await main.get_inventory_valuation_report_record(db_session, auth)

    assert report.total_valuation == 0.0
    assert report.total_units_on_hand == 5
    assert report.parts_counted == 2
    assert report.parts_missing_cost_count == 1


async def test_inventory_valuation_report_lists_low_stock_parts_with_vendor(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor = await main.create_vendor_record(vendor_payload(name="NAPA"), db_session, auth)
    low_stock = await main.create_part_record(
        part_payload(
            part_number="BP-5",
            quantity_on_hand=1,
            reorder_threshold=2,
            vendor_id=vendor.id,
        ),
        db_session,
        auth,
    )
    await main.create_part_record(
        part_payload(part_number="BP-6", quantity_on_hand=10, reorder_threshold=2),
        db_session,
        auth,
    )
    await main.create_part_record(
        part_payload(part_number="BP-7", quantity_on_hand=0, reorder_threshold=None),
        db_session,
        auth,
    )

    report = await main.get_inventory_valuation_report_record(db_session, auth)

    assert len(report.low_stock_parts) == 1
    low = report.low_stock_parts[0]
    assert low.part_id == low_stock.id
    assert low.part_number == "BP-5"
    assert low.quantity_on_hand == 1
    assert low.reorder_threshold == 2
    assert low.vendor_display_name == "NAPA"


async def test_inventory_valuation_report_excludes_archived_parts(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    part = await main.create_part_record(
        part_payload(part_number="BP-8", quantity_on_hand=6, unit_cost=5.0),
        db_session,
        auth,
    )
    await main.archive_part_record(part.id, db_session, auth)

    report = await main.get_inventory_valuation_report_record(db_session, auth)

    assert report.total_valuation == 0.0
    assert report.total_units_on_hand == 0
    assert report.parts_counted == 0


async def test_inventory_valuation_report_cross_user_isolation(
    settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(db_session, username="inventory-isolation-other", password="other-password-123")
    _, other_response = await login_as(
        settings, db_session, username="inventory-isolation-other", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    await main.create_part_record(
        part_payload(part_number="BP-9", quantity_on_hand=5, unit_cost=8.0),
        db_session,
        owner_auth,
    )

    other_report = await main.get_inventory_valuation_report_record(db_session, other_auth)
    assert other_report.total_valuation == 0.0
    assert other_report.parts_counted == 0
    assert other_report.low_stock_parts == []


# ---- Parts usage report ----


async def test_parts_usage_report_sums_costed_usage(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    await _use_part(
        monkeypatch, settings, db_session, auth, unit_cost=10.0, quantity=3, vin="1FTFW1ET1EFA00195"
    )

    report = await main.get_parts_usage_report_record(db_session, auth, None, None)

    assert len(report.parts) == 1
    entry = report.parts[0]
    assert entry.quantity_used == 3
    assert entry.cost_total == pytest.approx(30.0)
    assert entry.quantity_missing_cost == 0
    assert report.total_quantity_used == 3
    assert report.total_cost == pytest.approx(30.0)
    assert report.total_quantity_missing_cost == 0


async def test_parts_usage_report_flags_missing_cost_and_sorts_by_quantity(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    await _use_part(
        monkeypatch, settings, db_session, auth, unit_cost=None, quantity=2, vin="1FTFW1ET1EFA00194"
    )
    await _use_part(
        monkeypatch, settings, db_session, auth, unit_cost=5.0, quantity=6, vin="1FTFW1ET1EFA00193"
    )

    report = await main.get_parts_usage_report_record(db_session, auth, None, None)

    assert len(report.parts) == 2
    # Most-used part first, regardless of cost availability.
    assert report.parts[0].quantity_used == 6
    assert report.parts[1].quantity_used == 2
    assert report.parts[1].quantity_missing_cost == 2
    assert report.parts[1].cost_total == 0.0
    assert report.total_cost == pytest.approx(30.0)
    assert report.total_quantity_missing_cost == 2


async def test_parts_usage_report_date_range_excludes_out_of_window_usage(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    await _use_part(
        monkeypatch, settings, db_session, auth, unit_cost=10.0, quantity=1, vin="1FTFW1ET1EFA00192"
    )

    now = datetime.now(UTC)
    report = await main.get_parts_usage_report_record(
        db_session, auth, now - timedelta(days=10), now - timedelta(days=5)
    )

    assert report.parts == []
    assert report.total_quantity_used == 0


async def test_parts_usage_report_invalid_date_range_rejected(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    now = datetime.now(UTC)
    with pytest.raises(HTTPException) as excinfo:
        await main.get_parts_usage_report_record(db_session, auth, now, now - timedelta(days=1))
    assert excinfo.value.status_code == 422


async def test_parts_usage_report_cross_user_isolation(
    monkeypatch, settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(db_session, username="parts-usage-isolation-other", password="other-password-123")
    _, other_response = await login_as(
        settings, db_session, username="parts-usage-isolation-other", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    await _use_part(
        monkeypatch,
        settings,
        db_session,
        owner_auth,
        unit_cost=10.0,
        quantity=1,
        vin="1FTFW1ET1EFA00191",
    )

    other_report = await main.get_parts_usage_report_record(db_session, other_auth, None, None)
    assert other_report.parts == []
    assert other_report.total_quantity_used == 0


# ---- Vendor purchasing report ----


async def _create_vendor_and_part(
    db_session: Session, auth, *, vendor_name: str = "AutoZone Commercial"
):
    vendor = await main.create_vendor_record(vendor_payload(name=vendor_name), db_session, auth)
    part = await main.create_part_record(
        part_payload(part_number=f"VP-{vendor_name[:4]}", vendor_id=vendor.id), db_session, auth
    )
    return vendor, part


async def _create_and_submit_po(
    db_session: Session, auth, vendor, part, *, unit_cost: float, quantity: int
):
    created = await main.create_purchase_order_record(
        PurchaseOrderCreate(
            vendor_id=vendor.id,
            line_items=[
                PurchaseOrderLineItemCreate(
                    part_id=part.id, quantity_ordered=quantity, unit_cost=unit_cost
                )
            ],
        ),
        db_session,
        auth,
    )
    return await main.submit_purchase_order_record(created.id, db_session, auth)


async def test_vendor_purchasing_report_sums_submitted_orders_by_vendor(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(db_session, auth)
    await _create_and_submit_po(db_session, auth, vendor, part, unit_cost=10.0, quantity=5)
    await _create_and_submit_po(db_session, auth, vendor, part, unit_cost=20.0, quantity=2)

    report = await main.get_vendor_purchasing_report_record(db_session, auth, None, None)

    assert report.total_orders == 2
    assert report.total_spend == pytest.approx(90.0)
    assert len(report.by_vendor) == 1
    assert report.by_vendor[0].vendor_id == vendor.id
    assert report.by_vendor[0].order_count == 2
    assert report.by_vendor[0].total_spend == pytest.approx(90.0)
    assert report.cancelled_order_count == 0


async def test_vendor_purchasing_report_excludes_drafts_and_discloses_cancelled_orders(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(db_session, auth)

    # Draft: never submitted, never a real commitment -- excluded entirely.
    await main.create_purchase_order_record(
        PurchaseOrderCreate(
            vendor_id=vendor.id,
            line_items=[
                PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=1, unit_cost=1.0)
            ],
        ),
        db_session,
        auth,
    )

    # Submitted then cancelled -- excluded from spend, counted separately.
    submitted = await _create_and_submit_po(
        db_session, auth, vendor, part, unit_cost=50.0, quantity=1
    )
    await main.cancel_purchase_order_record(submitted.id, db_session, auth)

    report = await main.get_vendor_purchasing_report_record(db_session, auth, None, None)

    assert report.total_orders == 0
    assert report.total_spend == 0.0
    assert report.by_vendor == []
    assert report.cancelled_order_count == 1


async def test_vendor_purchasing_report_counts_received_orders_as_spend(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(db_session, auth)
    submitted = await _create_and_submit_po(
        db_session, auth, vendor, part, unit_cost=10.0, quantity=3
    )
    await main.receive_purchase_order_record(
        submitted.id,
        PurchaseOrderReceiveRequest(line_item_id=submitted.line_items[0].id, quantity=3),
        db_session,
        auth,
    )

    report = await main.get_vendor_purchasing_report_record(db_session, auth, None, None)

    assert report.total_orders == 1
    assert report.total_spend == pytest.approx(30.0)
    assert report.cancelled_order_count == 0


async def test_vendor_purchasing_report_partially_received_then_cancelled_excludes_full_total(
    settings, db_session: Session
) -> None:
    """Pins a known, disclosed imprecision (see the docstring on
    `report_store.get_vendor_purchasing_report`): a PO cancelled from
    `partially_received` has some real, already-received spend, but this
    report excludes the order's *entire* total from spend anyway, since
    `PurchaseOrder.total` isn't reduced by partial receiving. The exclusion
    is at least surfaced via `cancelled_order_count`, not hidden entirely."""
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(db_session, auth)
    submitted = await _create_and_submit_po(
        db_session, auth, vendor, part, unit_cost=10.0, quantity=4
    )
    partially_received = await main.receive_purchase_order_record(
        submitted.id,
        PurchaseOrderReceiveRequest(line_item_id=submitted.line_items[0].id, quantity=2),
        db_session,
        auth,
    )
    assert partially_received.status == "partially_received"
    await main.cancel_purchase_order_record(partially_received.id, db_session, auth)

    report = await main.get_vendor_purchasing_report_record(db_session, auth, None, None)

    assert report.total_orders == 0
    assert report.total_spend == 0.0
    assert report.cancelled_order_count == 1


async def test_vendor_purchasing_report_date_range_excludes_out_of_window_orders(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(db_session, auth)
    await _create_and_submit_po(db_session, auth, vendor, part, unit_cost=10.0, quantity=1)

    now = datetime.now(UTC)
    report = await main.get_vendor_purchasing_report_record(
        db_session, auth, now - timedelta(days=10), now - timedelta(days=5)
    )

    assert report.total_orders == 0
    assert report.by_vendor == []


async def test_vendor_purchasing_report_invalid_date_range_rejected(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    now = datetime.now(UTC)
    with pytest.raises(HTTPException) as excinfo:
        await main.get_vendor_purchasing_report_record(
            db_session, auth, now, now - timedelta(days=1)
        )
    assert excinfo.value.status_code == 422


async def test_vendor_purchasing_report_cross_user_isolation(settings, db_session: Session) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(
        db_session, username="vendor-purchasing-isolation-other", password="other-password-123"
    )
    _, other_response = await login_as(
        settings,
        db_session,
        username="vendor-purchasing-isolation-other",
        password="other-password-123",
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    vendor, part = await _create_vendor_and_part(db_session, owner_auth)
    await _create_and_submit_po(db_session, owner_auth, vendor, part, unit_cost=10.0, quantity=1)

    other_report = await main.get_vendor_purchasing_report_record(
        db_session, other_auth, None, None
    )
    assert other_report.total_orders == 0
    assert other_report.by_vendor == []


# ---- Work order cycle time & comebacks report ----


def _set_cycle_time(db_session: Session, work_order_id: int, *, hours: float) -> None:
    """Directly back-dates a completed work order's creation timestamp so its
    cycle time is deterministic, mirroring the direct-timestamp-manipulation
    style already used by `_add_time_entry` for technician-time tests --
    real request timing in a test is near-instant and can't otherwise
    exercise a specific elapsed duration."""
    completed_event = db_session.scalars(
        select(WorkOrderStatusEvent).where(
            WorkOrderStatusEvent.work_order_id == work_order_id,
            WorkOrderStatusEvent.to_status == "completed",
        )
    ).one()
    work_order = db_session.get(WorkOrder, work_order_id)
    assert work_order is not None
    work_order.created_at = completed_event.created_at - timedelta(hours=hours)
    db_session.add(work_order)
    db_session.commit()


async def test_work_order_cycle_time_report_computes_average_median_fastest_slowest(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    work_order_a, _ = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth, vin="1FTFW1ET1EFA00390"
    )
    _set_cycle_time(db_session, work_order_a.id, hours=10)
    work_order_b, _ = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth, vin="1FTFW1ET1EFA00391"
    )
    _set_cycle_time(db_session, work_order_b.id, hours=20)
    work_order_c, _ = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth, vin="1FTFW1ET1EFA00392"
    )
    _set_cycle_time(db_session, work_order_c.id, hours=30)

    report = await main.get_work_order_cycle_time_report_record(db_session, auth, None, None)

    assert report.completed_work_order_count == 3
    assert report.average_cycle_time_hours == pytest.approx(20.0)
    assert report.median_cycle_time_hours == pytest.approx(20.0)
    assert report.fastest_cycle_time_hours == pytest.approx(10.0)
    assert report.slowest_cycle_time_hours == pytest.approx(30.0)
    assert report.comeback_count == 0
    assert report.comeback_rate_percent == 0.0


async def test_work_order_cycle_time_report_computes_median_for_even_count(
    monkeypatch, settings, db_session: Session
) -> None:
    """Pins the even-count branch of the median calculation separately from
    the odd-count case above -- 1h/2h/3h/100h has a median of (2+3)/2=2.5,
    clearly distinct from the average (26.5), so this can't accidentally
    pass under the wrong formula."""
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    hours_values = [1, 2, 3, 100]
    for index, hours in enumerate(hours_values):
        work_order, _ = await create_completed_work_order_with_invoice(
            monkeypatch, settings, db_session, auth, vin=f"1FTFW1ET1EFA0038{index}"
        )
        _set_cycle_time(db_session, work_order.id, hours=hours)

    report = await main.get_work_order_cycle_time_report_record(db_session, auth, None, None)

    assert report.completed_work_order_count == 4
    assert report.median_cycle_time_hours == pytest.approx(2.5)
    assert report.average_cycle_time_hours == pytest.approx(26.5)


async def test_work_order_cycle_time_report_computes_comeback_rate_from_manual_flag(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    comeback_work_order, _ = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth, vin="1FTFW1ET1EFA00393"
    )
    await main.update_work_order_record(
        comeback_work_order.id, WorkOrderUpdate(is_comeback=True), db_session, auth
    )
    await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth, vin="1FTFW1ET1EFA00394"
    )

    report = await main.get_work_order_cycle_time_report_record(db_session, auth, None, None)

    assert report.completed_work_order_count == 2
    assert report.comeback_count == 1
    assert report.comeback_rate_percent == pytest.approx(50.0)


async def test_work_order_cycle_time_report_empty_state_returns_zeros(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    report = await main.get_work_order_cycle_time_report_record(db_session, auth, None, None)

    assert report.completed_work_order_count == 0
    assert report.average_cycle_time_hours == 0.0
    assert report.median_cycle_time_hours == 0.0
    assert report.fastest_cycle_time_hours == 0.0
    assert report.slowest_cycle_time_hours == 0.0
    assert report.comeback_count == 0
    assert report.comeback_rate_percent == 0.0


async def test_work_order_cycle_time_report_date_range_excludes_out_of_window_completions(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth, vin="1FTFW1ET1EFA00395"
    )

    now = datetime.now(UTC)
    report = await main.get_work_order_cycle_time_report_record(
        db_session, auth, now - timedelta(days=10), now - timedelta(days=5)
    )

    assert report.completed_work_order_count == 0


async def test_work_order_cycle_time_report_invalid_date_range_rejected(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    now = datetime.now(UTC)
    with pytest.raises(HTTPException) as excinfo:
        await main.get_work_order_cycle_time_report_record(
            db_session, auth, now, now - timedelta(days=1)
        )
    assert excinfo.value.status_code == 422


async def test_work_order_cycle_time_report_cross_user_isolation(
    monkeypatch, settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(db_session, username="cycle-time-isolation-other", password="other-password-123")
    _, other_response = await login_as(
        settings, db_session, username="cycle-time-isolation-other", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, owner_auth, vin="1FTFW1ET1EFA00396"
    )

    other_report = await main.get_work_order_cycle_time_report_record(
        db_session, other_auth, None, None
    )
    assert other_report.completed_work_order_count == 0


# ---- Diagnostic findings & inspections report ----


async def test_diagnostic_inspection_report_counts_findings_and_missing_conclusion(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(
            vehicle_id=vehicle.id,
            symptoms="Rough idle at startup.",
            conclusion="Replaced ignition coil #3.",
        ),
        db_session,
        auth,
    )
    await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Intermittent stall."),
        db_session,
        auth,
    )

    report = await main.get_diagnostic_inspection_report_record(db_session, auth, None, None)

    assert report.diagnostic_finding_count == 2
    assert report.findings_missing_conclusion == 1
    assert report.inspection_count == 0
    assert report.inspection_item_count == 0


async def test_diagnostic_inspection_report_breaks_down_inspection_item_status(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    await main.create_inspection_record(
        InspectionCreate(
            vehicle_id=vehicle.id,
            inspection_type="Multi-point",
            items=[
                InspectionItem(label="Brake pads", status="ok"),
                InspectionItem(label="Tire tread", status="attention", note="4/32 remaining"),
                InspectionItem(label="Battery", status="fail", note="Below minimum voltage"),
            ],
        ),
        db_session,
        auth,
    )
    await main.create_inspection_record(
        InspectionCreate(
            vehicle_id=vehicle.id,
            items=[InspectionItem(label="Wipers", status="ok")],
        ),
        db_session,
        auth,
    )

    report = await main.get_diagnostic_inspection_report_record(db_session, auth, None, None)

    assert report.inspection_count == 2
    assert report.inspection_item_count == 4
    assert report.items_ok == 2
    assert report.items_attention == 1
    assert report.items_fail == 1
    assert report.diagnostic_finding_count == 0


async def test_diagnostic_inspection_report_counts_inspection_with_no_items_yet(
    settings, db_session: Session
) -> None:
    """A technician can start an inspection before filling in any checklist
    items -- should still count toward inspection_count with zero items,
    not be skipped or error."""
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id, items=[]),
        db_session,
        auth,
    )

    report = await main.get_diagnostic_inspection_report_record(db_session, auth, None, None)

    assert report.inspection_count == 1
    assert report.inspection_item_count == 0
    assert report.items_ok == 0
    assert report.items_attention == 0
    assert report.items_fail == 0


async def test_diagnostic_inspection_report_counts_archived_activity_in_the_window(
    settings, db_session: Session
) -> None:
    """Activity is counted by when it was created, not by current archived
    status -- archiving afterward is an administrative action, not a
    retroactive undo. See the response model's docstring."""
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    finding = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Squeaking brakes."),
        db_session,
        auth,
    )
    await main.archive_diagnostic_finding_record(finding.id, db_session, auth)

    report = await main.get_diagnostic_inspection_report_record(db_session, auth, None, None)

    assert report.diagnostic_finding_count == 1
    assert report.findings_missing_conclusion == 1


async def test_diagnostic_inspection_report_empty_state_returns_zeros(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    report = await main.get_diagnostic_inspection_report_record(db_session, auth, None, None)

    assert report.diagnostic_finding_count == 0
    assert report.findings_missing_conclusion == 0
    assert report.inspection_count == 0
    assert report.inspection_item_count == 0
    assert report.items_ok == 0
    assert report.items_attention == 0
    assert report.items_fail == 0


async def test_diagnostic_inspection_report_date_range_excludes_out_of_window_activity(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)
    await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Check engine light."),
        db_session,
        auth,
    )

    now = datetime.now(UTC)
    report = await main.get_diagnostic_inspection_report_record(
        db_session, auth, now - timedelta(days=10), now - timedelta(days=5)
    )

    assert report.diagnostic_finding_count == 0


async def test_diagnostic_inspection_report_invalid_date_range_rejected(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    now = datetime.now(UTC)
    with pytest.raises(HTTPException) as excinfo:
        await main.get_diagnostic_inspection_report_record(
            db_session, auth, now, now - timedelta(days=1)
        )
    assert excinfo.value.status_code == 422


async def test_diagnostic_inspection_report_cross_user_isolation(
    settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(
        db_session, username="diag-inspection-isolation-other", password="other-password-123"
    )
    _, other_response = await login_as(
        settings,
        db_session,
        username="diag-inspection-isolation-other",
        password="other-password-123",
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    vehicle = await _create_vehicle(settings, db_session, owner_auth)
    await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Grinding noise."),
        db_session,
        owner_auth,
    )
    await main.create_inspection_record(
        InspectionCreate(
            vehicle_id=vehicle.id, items=[InspectionItem(label="Oil level", status="ok")]
        ),
        db_session,
        owner_auth,
    )

    other_report = await main.get_diagnostic_inspection_report_record(
        db_session, other_auth, None, None
    )
    assert other_report.diagnostic_finding_count == 0
    assert other_report.inspection_count == 0
