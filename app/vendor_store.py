from __future__ import annotations

import re

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id, ensure_utc
from app.config import Settings
from app.db_models import Part, Vendor
from app.models import (
    VendorArchiveResponse,
    VendorCreate,
    VendorListResponse,
    VendorRead,
    VendorUpdate,
)
from app.shop_store import resolve_shop_id

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class VendorStoreError(ValueError):
    pass


class VendorNotFoundError(VendorStoreError):
    pass


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not _EMAIL_RE.fullmatch(normalized):
        raise VendorStoreError("Email address is invalid.")
    return normalized


def normalize_phone(value: str | None) -> tuple[str, str] | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    digits = "".join(character for character in stripped if character.isdigit())
    if len(digits) < 7 or len(digits) > 15:
        raise VendorStoreError("Phone number must contain between 7 and 15 digits.")
    if len(digits) == 10:
        display = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    elif len(digits) == 7:
        display = f"{digits[:3]}-{digits[3:]}"
    else:
        display = f"+{digits}"
    return display, digits


def normalize_vendor_fields(payload: VendorCreate | VendorUpdate) -> dict[str, object]:
    email = normalize_email(payload.email)
    phone = normalize_phone(payload.phone)
    return {
        "name": payload.name,
        "contact_name": payload.contact_name,
        "phone": phone[0] if phone else None,
        "phone_normalized": phone[1] if phone else None,
        "email": email,
        "email_normalized": email,
        "address_line_1": payload.address_line_1,
        "address_line_2": payload.address_line_2,
        "city": payload.city,
        "state": payload.state,
        "postal_code": payload.postal_code,
        "notes": payload.notes,
    }


def _owner_query(auth: AuthContext) -> Select[tuple[Vendor]]:
    return select(Vendor).where(Vendor.owner_user_id == effective_owner_id(auth))


def _get_vendor(db: Session, auth: AuthContext, vendor_id: int) -> Vendor:
    vendor = db.scalar(_owner_query(auth).where(Vendor.id == vendor_id))
    if vendor is None:
        raise VendorNotFoundError("Vendor not found.")
    return vendor


def _to_read(db: Session, vendor: Vendor) -> VendorRead:
    part_count = (
        db.scalar(
            select(func.count())
            .select_from(Part)
            .where(Part.vendor_id == vendor.id, Part.is_archived.is_(False))
        )
        or 0
    )
    return VendorRead(
        id=vendor.id,
        name=vendor.name,
        contact_name=vendor.contact_name,
        phone=vendor.phone,
        email=vendor.email,
        address_line_1=vendor.address_line_1,
        address_line_2=vendor.address_line_2,
        city=vendor.city,
        state=vendor.state,
        postal_code=vendor.postal_code,
        notes=vendor.notes,
        is_archived=vendor.is_archived,
        part_count=part_count,
        created_at=ensure_utc(vendor.created_at),
        updated_at=ensure_utc(vendor.updated_at),
    )


def create_vendor(*, db: Session, auth: AuthContext, payload: VendorCreate) -> VendorRead:
    normalized = normalize_vendor_fields(payload)
    vendor = Vendor(
        owner_user_id=effective_owner_id(auth), shop_id=resolve_shop_id(db, auth), **normalized
    )
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return _to_read(db, vendor)


def get_vendor(*, db: Session, auth: AuthContext, vendor_id: int) -> VendorRead:
    return _to_read(db, _get_vendor(db, auth, vendor_id))


def get_vendor_model(*, db: Session, auth: AuthContext, vendor_id: int) -> Vendor:
    return _get_vendor(db, auth, vendor_id)


def update_vendor(
    *, db: Session, auth: AuthContext, vendor_id: int, payload: VendorUpdate
) -> VendorRead:
    vendor = _get_vendor(db, auth, vendor_id)
    normalized = normalize_vendor_fields(payload)
    field_map = {
        "name": ["name"],
        "contact_name": ["contact_name"],
        "phone": ["phone", "phone_normalized"],
        "email": ["email", "email_normalized"],
        "address_line_1": ["address_line_1"],
        "address_line_2": ["address_line_2"],
        "city": ["city"],
        "state": ["state"],
        "postal_code": ["postal_code"],
        "notes": ["notes"],
    }
    for payload_field, target_fields in field_map.items():
        if payload_field not in payload.model_fields_set:
            continue
        for target_field in target_fields:
            setattr(vendor, target_field, normalized[target_field])
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return _to_read(db, vendor)


def archive_vendor(*, db: Session, auth: AuthContext, vendor_id: int) -> VendorArchiveResponse:
    vendor = _get_vendor(db, auth, vendor_id)
    vendor.is_archived = True
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return VendorArchiveResponse(vendor=_to_read(db, vendor))


def list_vendors(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    archived: bool,
    search: str | None,
) -> VendorListResponse:
    if page_size > settings.customers_max_page_size:
        raise VendorStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise VendorStoreError("Page must be 1 or greater.")

    query = _owner_query(auth).where(Vendor.is_archived == archived)
    if search:
        lowered_tokens = [token for token in search.strip().lower().split() if token]
        for token in lowered_tokens:
            clause = or_(
                func.lower(Vendor.name).contains(token),
                func.lower(func.coalesce(Vendor.contact_name, "")).contains(token),
                func.lower(func.coalesce(Vendor.email_normalized, "")).contains(token),
            )
            query = query.where(clause)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    vendors = db.scalars(
        query.order_by(Vendor.updated_at.desc(), Vendor.id.desc()).offset(offset).limit(page_size)
    ).all()
    return VendorListResponse(
        items=[_to_read(db, vendor) for vendor in vendors],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(vendors) < total,
    )
