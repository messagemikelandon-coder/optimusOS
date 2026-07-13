from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id, ensure_utc
from app.config import Settings
from app.db_models import Part, Vendor
from app.models import PartArchiveResponse, PartCreate, PartListResponse, PartRead, PartUpdate


class PartStoreError(ValueError):
    pass


class PartNotFoundError(PartStoreError):
    pass


def _decimal_money(value: float | None, field_label: str) -> Decimal | None:
    if value is None:
        return None
    try:
        normalized = Decimal(str(value))
    except InvalidOperation as exc:
        raise PartStoreError(f"{field_label} is invalid.") from exc
    if not normalized.is_finite() or normalized < 0:
        raise PartStoreError(f"{field_label} must be zero or greater.")
    return normalized.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _validate_vendor(db: Session, auth: AuthContext, vendor_id: int | None) -> None:
    if vendor_id is None:
        return
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == vendor_id, Vendor.owner_user_id == effective_owner_id(auth)
        )
    )
    if vendor is None:
        raise PartStoreError("Selected vendor was not found.")


def normalize_part_fields(payload: PartCreate | PartUpdate) -> dict[str, object]:
    return {
        "part_number": payload.part_number,
        "description": payload.description,
        "category": payload.category,
        "quantity_on_hand": payload.quantity_on_hand,
        "reorder_threshold": payload.reorder_threshold,
        "unit_cost": _decimal_money(payload.unit_cost, "Unit cost"),
        "unit_price": _decimal_money(payload.unit_price, "Unit price"),
        "location": payload.location,
        "notes": payload.notes,
        "vendor_id": payload.vendor_id,
    }


def _owner_query(auth: AuthContext) -> Select[tuple[Part]]:
    return select(Part).where(Part.owner_user_id == effective_owner_id(auth))


def _get_part(db: Session, auth: AuthContext, part_id: int) -> Part:
    part = db.scalar(_owner_query(auth).where(Part.id == part_id))
    if part is None:
        raise PartNotFoundError("Part not found.")
    return part


def _to_read(db: Session, auth: AuthContext, part: Part) -> PartRead:
    vendor_name = None
    if part.vendor_id is not None:
        vendor_name = db.scalar(
            select(Vendor.name).where(
                Vendor.id == part.vendor_id, Vendor.owner_user_id == effective_owner_id(auth)
            )
        )
    below_threshold = (
        part.reorder_threshold is not None and part.quantity_on_hand <= part.reorder_threshold
    )
    return PartRead(
        id=part.id,
        part_number=part.part_number,
        description=part.description,
        category=part.category,
        quantity_on_hand=part.quantity_on_hand,
        reorder_threshold=part.reorder_threshold,
        unit_cost=float(part.unit_cost) if part.unit_cost is not None else None,
        unit_price=float(part.unit_price) if part.unit_price is not None else None,
        location=part.location,
        notes=part.notes,
        vendor_id=part.vendor_id,
        vendor_name=vendor_name,
        is_archived=part.is_archived,
        is_below_reorder_threshold=below_threshold,
        created_at=ensure_utc(part.created_at),
        updated_at=ensure_utc(part.updated_at),
    )


def create_part(*, db: Session, auth: AuthContext, payload: PartCreate) -> PartRead:
    _validate_vendor(db, auth, payload.vendor_id)
    normalized = normalize_part_fields(payload)
    part = Part(owner_user_id=effective_owner_id(auth), **normalized)
    db.add(part)
    db.commit()
    db.refresh(part)
    return _to_read(db, auth, part)


def get_part(*, db: Session, auth: AuthContext, part_id: int) -> PartRead:
    return _to_read(db, auth, _get_part(db, auth, part_id))


def update_part(*, db: Session, auth: AuthContext, part_id: int, payload: PartUpdate) -> PartRead:
    part = _get_part(db, auth, part_id)
    if "vendor_id" in payload.model_fields_set:
        _validate_vendor(db, auth, payload.vendor_id)
    normalized = normalize_part_fields(payload)
    field_map = {
        "part_number": ["part_number"],
        "description": ["description"],
        "category": ["category"],
        "quantity_on_hand": ["quantity_on_hand"],
        "reorder_threshold": ["reorder_threshold"],
        "unit_cost": ["unit_cost"],
        "unit_price": ["unit_price"],
        "location": ["location"],
        "notes": ["notes"],
        "vendor_id": ["vendor_id"],
    }
    for payload_field, target_fields in field_map.items():
        if payload_field not in payload.model_fields_set:
            continue
        for target_field in target_fields:
            setattr(part, target_field, normalized[target_field])
    db.add(part)
    db.commit()
    db.refresh(part)
    return _to_read(db, auth, part)


def archive_part(*, db: Session, auth: AuthContext, part_id: int) -> PartArchiveResponse:
    part = _get_part(db, auth, part_id)
    part.is_archived = True
    db.add(part)
    db.commit()
    db.refresh(part)
    return PartArchiveResponse(part=_to_read(db, auth, part))


def list_parts(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    archived: bool,
    search: str | None,
    vendor_id: int | None = None,
    below_reorder_threshold_only: bool = False,
) -> PartListResponse:
    if page_size > settings.customers_max_page_size:
        raise PartStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise PartStoreError("Page must be 1 or greater.")

    query = _owner_query(auth).where(Part.is_archived == archived)
    if vendor_id is not None:
        query = query.where(Part.vendor_id == vendor_id)
    if below_reorder_threshold_only:
        query = query.where(
            Part.reorder_threshold.is_not(None),
            Part.quantity_on_hand <= Part.reorder_threshold,
        )
    if search:
        lowered_tokens = [token for token in search.strip().lower().split() if token]
        for token in lowered_tokens:
            clause = or_(
                func.lower(Part.part_number).contains(token),
                func.lower(Part.description).contains(token),
                func.lower(func.coalesce(Part.category, "")).contains(token),
            )
            query = query.where(clause)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    parts = db.scalars(
        query.order_by(Part.updated_at.desc(), Part.id.desc()).offset(offset).limit(page_size)
    ).all()
    return PartListResponse(
        items=[_to_read(db, auth, part) for part in parts],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(parts) < total,
    )
