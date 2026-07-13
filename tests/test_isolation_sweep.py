from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.main as main
from app.models import (
    CustomerUpdate,
    InvoicePaymentCreate,
    InvoicePaymentVoidRequest,
    PaymentAppliesTo,
    VehicleUpdate,
    WorkOrderNoteCreate,
    WorkOrderNoteVisibility,
)
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_payments_api import create_completed_work_order_with_invoice, issue
from tests.test_vehicles_api import create_customer_for_auth, vehicle_payload

pytestmark = pytest.mark.anyio


async def assert_cross_user_404(coro) -> None:  # type: ignore[no-untyped-def]
    """Shared assertion helper: every owner-scoped route must return exactly
    404 for a second owner's session, never a 403/500 that would otherwise
    leak the record's existence."""
    with pytest.raises(HTTPException) as excinfo:
        await coro
    assert excinfo.value.status_code == 404


async def test_second_owner_isolation_sweep_across_full_record_chain(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    """Phase 4 deliverable 2: build one full chain under owner A, then sweep
    every record type with a single owner-B session in one place. This does
    not re-derive isolation cases already proven per-slice elsewhere (see
    each store's own cross_user_isolation test); it closes the one
    confirmed pre-existing gap (vehicle update/archive/list were never
    isolation-tested) and proves the whole chain is isolated end to end from
    a single second-owner session, which no existing test does."""
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(db_session, username="isolation-sweep-other", password="other-password-123")
    _, other_response = await login_as(
        settings, db_session, username="isolation-sweep-other", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    customer_id = await create_customer_for_auth(settings, db_session, owner_auth)
    vehicle = await main.create_vehicle_record(
        customer_id, vehicle_payload(), db_session, owner_auth
    )
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, owner_auth, vin="2HGFC2F59JH500002"
    )
    issued = await issue(invoice.id, db_session, settings, owner_auth)
    paid = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(
            amount=issued.invoice_total, method_label="Cash", applies_to=PaymentAppliesTo.FULL
        ),
        db_session,
        owner_auth,
    )
    payment_id = paid.payments[0].id
    work_order = await main.get_work_order_record(paid.work_order_id, db_session, owner_auth)

    # Customers.
    listed = await main.list_customer_records(
        db_session, settings, other_auth, page=1, page_size=50, search=None, archived=False
    )
    assert customer_id not in {item.id for item in listed.items}
    await assert_cross_user_404(main.get_customer_record(customer_id, db_session, other_auth))
    await assert_cross_user_404(
        main.update_customer_record(
            customer_id, CustomerUpdate(city="Nowhere"), db_session, other_auth
        )
    )
    await assert_cross_user_404(main.archive_customer_record(customer_id, db_session, other_auth))
    await assert_cross_user_404(
        main.get_customer_history_record(customer_id, db_session, other_auth, limit=20)
    )

    # Vehicles -- closes the pre-existing gap: only GET was ever isolation-tested before.
    vehicle_listed = await main.list_vehicle_records(
        db_session,
        settings,
        other_auth,
        page=1,
        page_size=50,
        search=None,
        customer_id=None,
        archived=False,
    )
    assert vehicle.id not in {item.id for item in vehicle_listed.items}
    await assert_cross_user_404(main.get_vehicle_record(vehicle.id, db_session, other_auth))
    await assert_cross_user_404(
        main.update_vehicle_record(vehicle.id, VehicleUpdate(color="Red"), db_session, other_auth)
    )
    await assert_cross_user_404(main.archive_vehicle_record(vehicle.id, db_session, other_auth))

    # Work orders.
    await assert_cross_user_404(main.get_work_order_record(work_order.id, db_session, other_auth))
    await assert_cross_user_404(
        main.add_work_order_note_record(
            work_order.id,
            WorkOrderNoteCreate(
                note="cross-user attempt", visibility=WorkOrderNoteVisibility.INTERNAL
            ),
            db_session,
            other_auth,
        )
    )

    # Invoices.
    await assert_cross_user_404(main.get_invoice_record(issued.id, db_session, other_auth))
    await assert_cross_user_404(main.get_invoice_html(issued.id, db_session, settings, other_auth))
    await assert_cross_user_404(main.get_invoice_pdf(issued.id, db_session, settings, other_auth))

    # Payments.
    await assert_cross_user_404(
        main.record_invoice_payment(
            issued.id,
            InvoicePaymentCreate(
                amount=1.0, method_label="cash", applies_to=PaymentAppliesTo.OTHER
            ),
            db_session,
            other_auth,
        )
    )
    await assert_cross_user_404(
        main.void_invoice_payment(
            issued.id,
            payment_id,
            InvoicePaymentVoidRequest(reason="cross-user attempt"),
            db_session,
            other_auth,
        )
    )
