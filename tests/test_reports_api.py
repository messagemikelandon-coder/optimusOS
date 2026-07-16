from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.main as main
from app.auth import effective_owner_id
from app.db_models import TechnicianTimeEntry
from app.models import InvoicePaymentCreate, InvoicePaymentVoidRequest, PaymentAppliesTo
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
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
