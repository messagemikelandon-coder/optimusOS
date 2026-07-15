from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.main as main
from app.models import (
    PartUpdate,
    PurchaseOrderCreate,
    PurchaseOrderLineItemCreate,
    PurchaseOrderReceiveRequest,
)
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_vendors_and_parts_api import part_payload, vendor_payload

pytestmark = pytest.mark.anyio


async def _create_vendor_and_part(settings, db_session: Session, auth):
    vendor = await main.create_vendor_record(vendor_payload(), db_session, auth)
    part = await main.create_part_record(
        part_payload(vendor_id=vendor.id, quantity_on_hand=4), db_session, auth
    )
    return vendor, part


async def test_purchase_orders_require_authenticated_session(settings, db_session: Session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/purchase-orders"), db_session, settings)
    assert excinfo.value.status_code == 401


async def test_create_purchase_order_computes_totals_and_snapshots_unit_cost(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(settings, db_session, auth)

    created = await main.create_purchase_order_record(
        PurchaseOrderCreate(
            vendor_id=vendor.id,
            line_items=[
                PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=10, unit_cost=5.25)
            ],
        ),
        db_session,
        auth,
    )
    assert created.status == "draft"
    assert created.po_number.startswith("PO-")
    assert len(created.line_items) == 1
    assert created.line_items[0].quantity_ordered == 10
    assert created.line_items[0].quantity_received == 0
    assert created.line_items[0].unit_cost == 5.25
    assert created.line_items[0].line_total == 52.5
    assert created.subtotal == 52.5
    assert created.total == 52.5

    # Changing the part's own unit_cost afterward must not retroactively
    # change an already-created purchase order's line item -- it's a
    # snapshot at order time, matching the invoice line item convention.
    await main.update_part_record(part.id, PartUpdate(unit_cost=99.00), db_session, auth)
    refetched = await main.get_purchase_order_record(created.id, db_session, auth)
    assert refetched.line_items[0].unit_cost == 5.25


async def test_purchase_order_rejects_unknown_vendor_and_part(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(settings, db_session, auth)

    with pytest.raises(HTTPException) as vendor_exc:
        await main.create_purchase_order_record(
            PurchaseOrderCreate(
                vendor_id=999999,
                line_items=[
                    PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=1, unit_cost=1.0)
                ],
            ),
            db_session,
            auth,
        )
    assert vendor_exc.value.status_code == 422

    with pytest.raises(HTTPException) as part_exc:
        await main.create_purchase_order_record(
            PurchaseOrderCreate(
                vendor_id=vendor.id,
                line_items=[
                    PurchaseOrderLineItemCreate(part_id=999999, quantity_ordered=1, unit_cost=1.0)
                ],
            ),
            db_session,
            auth,
        )
    assert part_exc.value.status_code == 422


async def test_purchase_order_cross_owner_isolation(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    vendor, part = await _create_vendor_and_part(settings, db_session, owner_auth)

    created = await main.create_purchase_order_record(
        PurchaseOrderCreate(
            vendor_id=vendor.id,
            line_items=[
                PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=1, unit_cost=1.0)
            ],
        ),
        db_session,
        owner_auth,
    )

    with pytest.raises(HTTPException) as get_exc:
        await main.get_purchase_order_record(created.id, db_session, other_auth)
    assert get_exc.value.status_code == 404

    # A second owner cannot even reference the first owner's vendor/part.
    other_vendor = await main.create_vendor_record(vendor_payload(), db_session, other_auth)
    with pytest.raises(HTTPException) as cross_part_exc:
        await main.create_purchase_order_record(
            PurchaseOrderCreate(
                vendor_id=other_vendor.id,
                line_items=[
                    PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=1, unit_cost=1.0)
                ],
            ),
            db_session,
            other_auth,
        )
    assert cross_part_exc.value.status_code == 422


async def test_purchase_order_status_transitions(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(settings, db_session, auth)
    created = await main.create_purchase_order_record(
        PurchaseOrderCreate(
            vendor_id=vendor.id,
            line_items=[
                PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=5, unit_cost=2.0)
            ],
        ),
        db_session,
        auth,
    )

    # Cannot receive against a draft PO.
    with pytest.raises(HTTPException) as premature_exc:
        await main.receive_purchase_order_record(
            created.id,
            PurchaseOrderReceiveRequest(line_item_id=created.line_items[0].id, quantity=1),
            db_session,
            auth,
        )
    assert premature_exc.value.status_code == 422

    submitted = await main.submit_purchase_order_record(created.id, db_session, auth)
    assert submitted.status == "submitted"

    # Cannot submit twice.
    with pytest.raises(HTTPException) as resubmit_exc:
        await main.submit_purchase_order_record(created.id, db_session, auth)
    assert resubmit_exc.value.status_code == 422

    cancelled_po = await main.create_purchase_order_record(
        PurchaseOrderCreate(
            vendor_id=vendor.id,
            line_items=[
                PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=1, unit_cost=1.0)
            ],
        ),
        db_session,
        auth,
    )
    cancelled = await main.cancel_purchase_order_record(cancelled_po.id, db_session, auth)
    assert cancelled.status == "cancelled"

    # Cannot transition out of a cancelled PO.
    with pytest.raises(HTTPException) as terminal_exc:
        await main.submit_purchase_order_record(cancelled_po.id, db_session, auth)
    assert terminal_exc.value.status_code == 422


async def test_receiving_updates_inventory_and_auto_transitions_status(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(settings, db_session, auth)
    starting_quantity = part.quantity_on_hand

    created = await main.create_purchase_order_record(
        PurchaseOrderCreate(
            vendor_id=vendor.id,
            line_items=[
                PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=10, unit_cost=3.0)
            ],
        ),
        db_session,
        auth,
    )
    await main.submit_purchase_order_record(created.id, db_session, auth)

    partial = await main.receive_purchase_order_record(
        created.id,
        PurchaseOrderReceiveRequest(
            line_item_id=created.line_items[0].id, quantity=4, note="First delivery"
        ),
        db_session,
        auth,
    )
    assert partial.status == "partially_received"
    assert partial.line_items[0].quantity_received == 4

    part_after_partial = await main.get_part_record(part.id, db_session, auth)
    assert part_after_partial.quantity_on_hand == starting_quantity + 4

    full = await main.receive_purchase_order_record(
        created.id,
        PurchaseOrderReceiveRequest(line_item_id=created.line_items[0].id, quantity=6),
        db_session,
        auth,
    )
    assert full.status == "received"
    assert full.line_items[0].quantity_received == 10

    part_after_full = await main.get_part_record(part.id, db_session, auth)
    assert part_after_full.quantity_on_hand == starting_quantity + 10

    receipts = await main.list_purchase_order_receipt_records(created.id, db_session, auth)
    assert [r.quantity_received for r in receipts.receipts] == [4, 6]
    assert receipts.receipts[0].note == "First delivery"
    assert receipts.receipts[0].received_by_display_name == "Owner"


async def test_receiving_rejects_over_receipt(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(settings, db_session, auth)

    created = await main.create_purchase_order_record(
        PurchaseOrderCreate(
            vendor_id=vendor.id,
            line_items=[
                PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=5, unit_cost=1.0)
            ],
        ),
        db_session,
        auth,
    )
    await main.submit_purchase_order_record(created.id, db_session, auth)

    await main.receive_purchase_order_record(
        created.id,
        PurchaseOrderReceiveRequest(line_item_id=created.line_items[0].id, quantity=4),
        db_session,
        auth,
    )

    # Only 1 unit remains -- receiving 2 more must be rejected outright, not
    # silently clamped, so a receiving mistake can't quietly overstate stock.
    with pytest.raises(HTTPException) as over_receipt_exc:
        await main.receive_purchase_order_record(
            created.id,
            PurchaseOrderReceiveRequest(line_item_id=created.line_items[0].id, quantity=2),
            db_session,
            auth,
        )
    assert over_receipt_exc.value.status_code == 422

    unchanged = await main.get_purchase_order_record(created.id, db_session, auth)
    assert unchanged.line_items[0].quantity_received == 4
    assert unchanged.status == "partially_received"


async def test_purchase_order_line_items_are_immutable_after_creation(
    settings, db_session: Session
) -> None:
    """No add/remove/edit-line-item endpoint exists by design (matching the
    estimate-revision convention: if the order is wrong, cancel and recreate
    rather than editing in place) -- quantity_ordered on a fetched purchase
    order stays exactly what was submitted at creation."""
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(settings, db_session, auth)
    created = await main.create_purchase_order_record(
        PurchaseOrderCreate(
            vendor_id=vendor.id,
            line_items=[
                PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=3, unit_cost=1.5)
            ],
        ),
        db_session,
        auth,
    )
    refetched = await main.get_purchase_order_record(created.id, db_session, auth)
    assert refetched.line_items[0].quantity_ordered == 3


async def test_purchase_order_rejects_line_items_that_would_overflow_the_money_column(
    settings, db_session: Session
) -> None:
    """Numeric(10, 2) money columns cap out at 99_999_999.99 -- a line item
    whose total would exceed that must be rejected with a clean validation
    error, not surface as a raw Postgres numeric-overflow error at commit
    time."""
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor, part = await _create_vendor_and_part(settings, db_session, auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_purchase_order_record(
            PurchaseOrderCreate(
                vendor_id=vendor.id,
                line_items=[
                    PurchaseOrderLineItemCreate(
                        part_id=part.id, quantity_ordered=100_000, unit_cost=99_999.99
                    )
                ],
            ),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422
