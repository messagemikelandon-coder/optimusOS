from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id, effective_shop_owner_id, ensure_utc
from app.config import Settings
from app.db_models import Part, PurchaseOrder, PurchaseOrderLineItem, PurchaseOrderReceipt, Vendor
from app.models import (
    PurchaseOrderCreate,
    PurchaseOrderLineItemRead,
    PurchaseOrderListResponse,
    PurchaseOrderRead,
    PurchaseOrderReceiptRead,
    PurchaseOrderReceiptsResponse,
    PurchaseOrderReceiveRequest,
    PurchaseOrderStatus,
)
from app.shop_store import resolve_shop_id

MONEY = Decimal("0.01")

TRANSITIONS: dict[PurchaseOrderStatus, tuple[PurchaseOrderStatus, ...]] = {
    PurchaseOrderStatus.DRAFT: (
        PurchaseOrderStatus.SUBMITTED,
        PurchaseOrderStatus.CANCELLED,
    ),
    PurchaseOrderStatus.SUBMITTED: (
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
        PurchaseOrderStatus.RECEIVED,
        PurchaseOrderStatus.CANCELLED,
    ),
    PurchaseOrderStatus.PARTIALLY_RECEIVED: (
        PurchaseOrderStatus.RECEIVED,
        PurchaseOrderStatus.CANCELLED,
    ),
    PurchaseOrderStatus.RECEIVED: (),
    PurchaseOrderStatus.CANCELLED: (),
}


class PurchaseOrderStoreError(ValueError):
    pass


class PurchaseOrderNotFoundError(PurchaseOrderStoreError):
    pass


def _money(value: float | Decimal, field_label: str = "Amount") -> Decimal:
    try:
        normalized = Decimal(str(value))
    except InvalidOperation as exc:
        raise PurchaseOrderStoreError(f"{field_label} is invalid.") from exc
    if not normalized.is_finite() or normalized < 0:
        raise PurchaseOrderStoreError(f"{field_label} must be zero or greater.")
    return normalized.quantize(MONEY, rounding=ROUND_HALF_UP)


def _owner_query(db: Session, auth: AuthContext) -> Select[tuple[PurchaseOrder]]:
    return select(PurchaseOrder).where(PurchaseOrder.shop_id == effective_shop_id(db, auth))


def _get_purchase_order(db: Session, auth: AuthContext, purchase_order_id: int) -> PurchaseOrder:
    purchase_order = db.scalar(_owner_query(db, auth).where(PurchaseOrder.id == purchase_order_id))
    if purchase_order is None:
        raise PurchaseOrderNotFoundError("Purchase order not found.")
    return purchase_order


def _validate_vendor(db: Session, auth: AuthContext, vendor_id: int) -> None:
    vendor = db.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.shop_id == effective_shop_id(db, auth))
    )
    if vendor is None:
        raise PurchaseOrderStoreError("Selected vendor was not found.")


def _require_part(db: Session, auth: AuthContext, part_id: int) -> Part:
    part = db.scalar(
        select(Part).where(Part.id == part_id, Part.shop_id == effective_shop_id(db, auth))
    )
    if part is None:
        raise PurchaseOrderStoreError("Selected part was not found.")
    return part


def _next_po_number(db: Session, auth: AuthContext) -> str:
    count = (
        db.scalar(
            select(func.count())
            .select_from(PurchaseOrder)
            .where(PurchaseOrder.shop_id == effective_shop_id(db, auth))
        )
        or 0
    )
    return f"PO-{effective_shop_owner_id(db, auth):03d}-{count + 1:05d}"


def _line_item_to_read(line_item: PurchaseOrderLineItem) -> PurchaseOrderLineItemRead:
    line_total = (line_item.unit_cost * line_item.quantity_ordered).quantize(
        MONEY, rounding=ROUND_HALF_UP
    )
    return PurchaseOrderLineItemRead(
        id=line_item.id,
        part_id=line_item.part_id,
        part_number=line_item.part.part_number,
        part_description=line_item.part.description,
        quantity_ordered=line_item.quantity_ordered,
        quantity_received=line_item.quantity_received,
        unit_cost=float(line_item.unit_cost),
        line_total=float(line_total),
    )


def _to_read(db: Session, auth: AuthContext, purchase_order: PurchaseOrder) -> PurchaseOrderRead:
    vendor_name = db.scalar(
        select(Vendor.name).where(
            Vendor.id == purchase_order.vendor_id,
            Vendor.shop_id == effective_shop_id(db, auth),
        )
    )
    return PurchaseOrderRead(
        id=purchase_order.id,
        po_number=purchase_order.po_number,
        vendor_id=purchase_order.vendor_id,
        vendor_name=vendor_name or "",
        status=PurchaseOrderStatus(purchase_order.status),
        notes=purchase_order.notes,
        line_items=[_line_item_to_read(item) for item in purchase_order.line_items],
        subtotal=float(purchase_order.subtotal),
        total=float(purchase_order.total),
        submitted_at=ensure_utc(purchase_order.submitted_at)
        if purchase_order.submitted_at
        else None,
        received_at=ensure_utc(purchase_order.received_at) if purchase_order.received_at else None,
        cancelled_at=ensure_utc(purchase_order.cancelled_at)
        if purchase_order.cancelled_at
        else None,
        created_at=ensure_utc(purchase_order.created_at),
        updated_at=ensure_utc(purchase_order.updated_at),
    )


def create_purchase_order(
    *, db: Session, auth: AuthContext, payload: PurchaseOrderCreate
) -> PurchaseOrderRead:
    _validate_vendor(db, auth, payload.vendor_id)
    # Numeric(10, 2) columns (unit_cost/line totals/subtotal/total) cap out
    # at 99_999_999.99 -- reject anything that would overflow that here with
    # a clean validation error, rather than letting a raw Postgres
    # numeric-overflow error surface as an unhandled 500 at commit time.
    numeric_column_max = Decimal("99999999.99")
    validated_items: list[tuple[int, Decimal, int]] = []
    subtotal = Decimal("0")
    for entry in payload.line_items:
        part = _require_part(db, auth, entry.part_id)
        if part.is_archived:
            raise PurchaseOrderStoreError(
                f"Part {part.part_number} is archived and cannot be ordered."
            )
        unit_cost = _money(entry.unit_cost, "Unit cost")
        line_total = (unit_cost * entry.quantity_ordered).quantize(MONEY, rounding=ROUND_HALF_UP)
        if line_total > numeric_column_max:
            raise PurchaseOrderStoreError(
                f"Line item total for part {part.part_number} is too large."
            )
        subtotal += line_total
        if subtotal > numeric_column_max:
            raise PurchaseOrderStoreError("Purchase order total is too large.")
        validated_items.append((entry.part_id, unit_cost, entry.quantity_ordered))

    # _next_po_number is a COUNT-then-format scheme, so two concurrent
    # creates for the same owner can generate the same po_number -- the
    # UNIQUE constraint on po_number catches that at commit time; retry with
    # a freshly recomputed number rather than surfacing a raw IntegrityError.
    max_attempts = 3
    for attempt in range(max_attempts):
        line_items = [
            PurchaseOrderLineItem(part_id=part_id, quantity_ordered=quantity, unit_cost=unit_cost)
            for part_id, unit_cost, quantity in validated_items
        ]
        purchase_order = PurchaseOrder(
            owner_user_id=effective_shop_owner_id(db, auth),
            shop_id=resolve_shop_id(db, auth),
            vendor_id=payload.vendor_id,
            po_number=_next_po_number(db, auth),
            status=PurchaseOrderStatus.DRAFT.value,
            notes=payload.notes,
            subtotal=subtotal,
            total=subtotal,
            created_by_user_id=auth.user.id,
            line_items=line_items,
        )
        db.add(purchase_order)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt == max_attempts - 1:
                raise PurchaseOrderStoreError(
                    "Could not generate a unique purchase order number; try again."
                ) from None
            continue
        db.refresh(purchase_order)
        return _to_read(db, auth, purchase_order)
    raise PurchaseOrderStoreError("Could not generate a unique purchase order number; try again.")


def get_purchase_order(
    *, db: Session, auth: AuthContext, purchase_order_id: int
) -> PurchaseOrderRead:
    return _to_read(db, auth, _get_purchase_order(db, auth, purchase_order_id))


def list_purchase_orders(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    status: PurchaseOrderStatus | None = None,
    vendor_id: int | None = None,
) -> PurchaseOrderListResponse:
    if page_size > settings.customers_max_page_size:
        raise PurchaseOrderStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise PurchaseOrderStoreError("Page must be 1 or greater.")

    query = _owner_query(db, auth)
    if status is not None:
        query = query.where(PurchaseOrder.status == status.value)
    if vendor_id is not None:
        query = query.where(PurchaseOrder.vendor_id == vendor_id)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    purchase_orders = db.scalars(
        query.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return PurchaseOrderListResponse(
        items=[_to_read(db, auth, purchase_order) for purchase_order in purchase_orders],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(purchase_orders) < total,
    )


def _transition(db: Session, purchase_order: PurchaseOrder, target: PurchaseOrderStatus) -> None:
    current = PurchaseOrderStatus(purchase_order.status)
    if target not in TRANSITIONS[current]:
        raise PurchaseOrderStoreError(
            f"Cannot move a purchase order from {current.value} to {target.value}."
        )
    purchase_order.status = target.value
    now = datetime.now(UTC)
    if target == PurchaseOrderStatus.SUBMITTED:
        purchase_order.submitted_at = now
    elif target == PurchaseOrderStatus.RECEIVED:
        purchase_order.received_at = now
    elif target == PurchaseOrderStatus.CANCELLED:
        purchase_order.cancelled_at = now
    db.add(purchase_order)


def submit_purchase_order(
    *, db: Session, auth: AuthContext, purchase_order_id: int
) -> PurchaseOrderRead:
    purchase_order = _get_purchase_order(db, auth, purchase_order_id)
    _transition(db, purchase_order, PurchaseOrderStatus.SUBMITTED)
    db.commit()
    db.refresh(purchase_order)
    return _to_read(db, auth, purchase_order)


def cancel_purchase_order(
    *, db: Session, auth: AuthContext, purchase_order_id: int
) -> PurchaseOrderRead:
    purchase_order = _get_purchase_order(db, auth, purchase_order_id)
    _transition(db, purchase_order, PurchaseOrderStatus.CANCELLED)
    db.commit()
    db.refresh(purchase_order)
    return _to_read(db, auth, purchase_order)


def receive_purchase_order_line_item(
    *,
    db: Session,
    auth: AuthContext,
    purchase_order_id: int,
    payload: PurchaseOrderReceiveRequest,
) -> PurchaseOrderRead:
    purchase_order = _get_purchase_order(db, auth, purchase_order_id)

    line_item_exists = db.scalar(
        select(PurchaseOrderLineItem.id).where(
            PurchaseOrderLineItem.id == payload.line_item_id,
            PurchaseOrderLineItem.purchase_order_id == purchase_order.id,
        )
    )
    if line_item_exists is None:
        raise PurchaseOrderStoreError("Selected line item was not found on this purchase order.")

    # Lock the purchase order and line item rows, then reload both with
    # populate_existing so every attribute read below reflects the
    # post-lock state -- not a value already cached in the session's
    # identity map from before the lock was acquired. A plain
    # `select(...).with_for_update()` against just the id column does NOT
    # refresh an already-loaded ORM object's other attributes, which would
    # let a concurrent request read stale pre-receipt quantities even while
    # correctly holding the row lock.
    db.execute(
        select(PurchaseOrder.id).where(PurchaseOrder.id == purchase_order.id).with_for_update()
    )
    line_item = db.scalar(
        select(PurchaseOrderLineItem)
        .where(PurchaseOrderLineItem.id == payload.line_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert line_item is not None
    db.refresh(purchase_order)

    current_status = PurchaseOrderStatus(purchase_order.status)
    if current_status not in (
        PurchaseOrderStatus.SUBMITTED,
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
    ):
        raise PurchaseOrderStoreError(
            "Only a submitted or partially received purchase order can receive parts."
        )

    remaining = line_item.quantity_ordered - line_item.quantity_received
    if payload.quantity > remaining:
        raise PurchaseOrderStoreError(
            f"Cannot receive {payload.quantity} units; only {remaining} remain on this line item."
        )

    line_item.quantity_received += payload.quantity
    db.add(line_item)

    part = db.scalar(
        select(Part)
        .where(Part.id == line_item.part_id, Part.shop_id == purchase_order.shop_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert part is not None
    part.quantity_on_hand += payload.quantity
    db.add(part)

    db.add(
        PurchaseOrderReceipt(
            purchase_order_id=purchase_order.id,
            line_item_id=line_item.id,
            owner_user_id=purchase_order.owner_user_id,
            shop_id=purchase_order.shop_id,
            quantity_received=payload.quantity,
            received_by_user_id=auth.user.id,
            received_by_name=auth.user.display_name,
            note=payload.note,
        )
    )

    db.flush()
    db.refresh(purchase_order)
    all_received = all(
        item.quantity_received >= item.quantity_ordered for item in purchase_order.line_items
    )
    fresh_status = PurchaseOrderStatus(purchase_order.status)
    if all_received:
        if fresh_status != PurchaseOrderStatus.RECEIVED:
            _transition(db, purchase_order, PurchaseOrderStatus.RECEIVED)
    elif fresh_status == PurchaseOrderStatus.SUBMITTED:
        _transition(db, purchase_order, PurchaseOrderStatus.PARTIALLY_RECEIVED)

    db.commit()
    db.refresh(purchase_order)
    return _to_read(db, auth, purchase_order)


def list_purchase_order_receipts(
    *, db: Session, auth: AuthContext, purchase_order_id: int
) -> PurchaseOrderReceiptsResponse:
    purchase_order = _get_purchase_order(db, auth, purchase_order_id)
    receipts = db.scalars(
        select(PurchaseOrderReceipt)
        .where(
            PurchaseOrderReceipt.purchase_order_id == purchase_order.id,
            PurchaseOrderReceipt.shop_id == purchase_order.shop_id,
        )
        .order_by(PurchaseOrderReceipt.created_at.asc(), PurchaseOrderReceipt.id.asc())
    ).all()
    return PurchaseOrderReceiptsResponse(
        purchase_order_id=purchase_order.id,
        receipts=[
            PurchaseOrderReceiptRead(
                id=receipt.id,
                line_item_id=receipt.line_item_id,
                quantity_received=receipt.quantity_received,
                received_by_display_name=receipt.received_by_name,
                note=receipt.note,
                created_at=ensure_utc(receipt.created_at),
            )
            for receipt in receipts
        ],
    )
