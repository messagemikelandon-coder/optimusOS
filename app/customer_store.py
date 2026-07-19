from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id, effective_shop_owner_id, ensure_utc
from app.config import Settings
from app.db_models import Customer
from app.models import (
    CustomerArchiveResponse,
    CustomerCreate,
    CustomerListResponse,
    CustomerRead,
    CustomerUpdate,
)
from app.shop_store import resolve_shop_id

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CustomerStoreError(ValueError):
    pass


class CustomerNotFoundError(CustomerStoreError):
    pass


@dataclass(frozen=True, slots=True)
class NormalizedPhone:
    display: str
    normalized: str


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not _EMAIL_RE.fullmatch(normalized):
        raise CustomerStoreError("Email address is invalid.")
    return normalized


def normalize_phone(value: str | None) -> NormalizedPhone | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    digits = "".join(character for character in stripped if character.isdigit())
    if len(digits) < 7 or len(digits) > 15:
        raise CustomerStoreError("Phone number must contain between 7 and 15 digits.")
    if len(digits) == 7:
        display = f"{digits[:3]}-{digits[3:]}"
    elif len(digits) == 10:
        display = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits.startswith("1"):
        display = f"+1 {digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    else:
        display = f"+{digits}"
    return NormalizedPhone(display=display, normalized=digits)


def normalize_customer_fields(payload: CustomerCreate | CustomerUpdate) -> dict[str, object]:
    email = normalize_email(payload.email)
    phone = normalize_phone(payload.phone)
    secondary_phone = normalize_phone(payload.secondary_phone)
    return {
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "company_name": payload.company_name,
        "email": email,
        "email_normalized": email,
        "phone": phone.display if phone else None,
        "phone_normalized": phone.normalized if phone else None,
        "secondary_phone": secondary_phone.display if secondary_phone else None,
        "secondary_phone_normalized": secondary_phone.normalized if secondary_phone else None,
        "address_line_1": payload.address_line_1,
        "address_line_2": payload.address_line_2,
        "city": payload.city,
        "state": payload.state,
        "postal_code": payload.postal_code,
        "preferred_contact_method": payload.preferred_contact_method.lower()
        if payload.preferred_contact_method
        else None,
        "internal_notes": payload.internal_notes,
    }


def validate_name_or_company(
    *, first_name: str | None, last_name: str | None, company_name: str | None
) -> None:
    if first_name or last_name or company_name:
        return
    raise CustomerStoreError("Provide a first or last name, or a company name.")


def display_name(customer: Customer) -> str:
    person_name = " ".join(part for part in [customer.first_name, customer.last_name] if part)
    if person_name and customer.company_name:
        return f"{person_name} ({customer.company_name})"
    return person_name or customer.company_name or "Unnamed customer"


def _to_read(customer: Customer) -> CustomerRead:
    return CustomerRead(
        id=customer.id,
        first_name=customer.first_name,
        last_name=customer.last_name,
        company_name=customer.company_name,
        email=customer.email,
        phone=customer.phone,
        secondary_phone=customer.secondary_phone,
        address_line_1=customer.address_line_1,
        address_line_2=customer.address_line_2,
        city=customer.city,
        state=customer.state,
        postal_code=customer.postal_code,
        preferred_contact_method=customer.preferred_contact_method,
        internal_notes=customer.internal_notes,
        display_name=display_name(customer),
        is_archived=customer.is_archived,
        created_at=ensure_utc(customer.created_at),
        updated_at=ensure_utc(customer.updated_at),
    )


def _owner_query(db: Session, auth: AuthContext) -> Select[tuple[Customer]]:
    return select(Customer).where(Customer.shop_id == effective_shop_id(db, auth))


def _get_customer(db: Session, auth: AuthContext, customer_id: int) -> Customer:
    customer = db.scalar(_owner_query(db, auth).where(Customer.id == customer_id))
    if customer is None:
        raise CustomerNotFoundError("Customer not found.")
    return customer


def get_customer_model(*, db: Session, auth: AuthContext, customer_id: int) -> Customer:
    return _get_customer(db, auth, customer_id)


def create_customer(
    *,
    db: Session,
    auth: AuthContext,
    payload: CustomerCreate,
) -> CustomerRead:
    normalized = normalize_customer_fields(payload)
    validate_name_or_company(
        first_name=normalized["first_name"],  # type: ignore[arg-type]
        last_name=normalized["last_name"],  # type: ignore[arg-type]
        company_name=normalized["company_name"],  # type: ignore[arg-type]
    )
    customer = Customer(
        owner_user_id=effective_shop_owner_id(db, auth),
        shop_id=resolve_shop_id(db, auth),
        **normalized,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return _to_read(customer)


def get_customer(*, db: Session, auth: AuthContext, customer_id: int) -> CustomerRead:
    return _to_read(_get_customer(db, auth, customer_id))


def update_customer(
    *,
    db: Session,
    auth: AuthContext,
    customer_id: int,
    payload: CustomerUpdate,
) -> CustomerRead:
    customer = _get_customer(db, auth, customer_id)
    normalized = normalize_customer_fields(payload)
    field_map = {
        "first_name": ["first_name"],
        "last_name": ["last_name"],
        "company_name": ["company_name"],
        "email": ["email", "email_normalized"],
        "phone": ["phone", "phone_normalized"],
        "secondary_phone": ["secondary_phone", "secondary_phone_normalized"],
        "address_line_1": ["address_line_1"],
        "address_line_2": ["address_line_2"],
        "city": ["city"],
        "state": ["state"],
        "postal_code": ["postal_code"],
        "preferred_contact_method": ["preferred_contact_method"],
        "internal_notes": ["internal_notes"],
    }
    for payload_field, target_fields in field_map.items():
        if payload_field not in payload.model_fields_set:
            continue
        for target_field in target_fields:
            setattr(customer, target_field, normalized[target_field])
    validate_name_or_company(
        first_name=customer.first_name,
        last_name=customer.last_name,
        company_name=customer.company_name,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return _to_read(customer)


def archive_customer(
    *,
    db: Session,
    auth: AuthContext,
    customer_id: int,
) -> CustomerArchiveResponse:
    customer = _get_customer(db, auth, customer_id)
    customer.is_archived = True
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return CustomerArchiveResponse(customer=_to_read(customer))


def list_customers(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    archived: bool,
    search: str | None,
) -> CustomerListResponse:
    if page_size > settings.customers_max_page_size:
        raise CustomerStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise CustomerStoreError("Page must be 1 or greater.")

    query = _owner_query(db, auth).where(Customer.is_archived == archived)
    if search:
        lowered_tokens = [token for token in search.strip().lower().split() if token]
        if lowered_tokens:
            token_clauses = []
            for token in lowered_tokens:
                name_clause = or_(
                    func.lower(func.coalesce(Customer.first_name, "")).contains(token),
                    func.lower(func.coalesce(Customer.last_name, "")).contains(token),
                    func.lower(func.coalesce(Customer.company_name, "")).contains(token),
                    func.lower(func.coalesce(Customer.email_normalized, "")).contains(token),
                )
                digits = "".join(character for character in token if character.isdigit())
                if digits:
                    name_clause = or_(
                        name_clause,
                        func.coalesce(Customer.phone_normalized, "").contains(digits),
                        func.coalesce(Customer.secondary_phone_normalized, "").contains(digits),
                    )
                token_clauses.append(name_clause)
            query = query.where(and_(*token_clauses))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    customers = db.scalars(
        query.order_by(Customer.updated_at.desc(), Customer.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return CustomerListResponse(
        items=[_to_read(customer) for customer in customers],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(customers) < total,
    )
