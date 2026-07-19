from __future__ import annotations

import re

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id, effective_shop_owner_id, ensure_utc
from app.config import Settings
from app.customer_store import create_customer
from app.db_models import IntakeRequest
from app.models import (
    CustomerCreate,
    IntakeRequestConvertRequest,
    IntakeRequestConvertResponse,
    IntakeRequestCreate,
    IntakeRequestListResponse,
    IntakeRequestRead,
    IntakeRequestUpdate,
    VehicleCreate,
)
from app.shop_store import resolve_shop_id
from app.vehicle_store import create_vehicle

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class IntakeStoreError(ValueError):
    pass


class IntakeRequestNotFoundError(IntakeStoreError):
    pass


class IntakeConflictError(IntakeStoreError):
    pass


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if not _EMAIL_RE.fullmatch(normalized):
        raise IntakeStoreError("Email address is invalid.")
    return normalized


def normalize_phone(value: str | None) -> tuple[str, str] | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    digits = "".join(character for character in stripped if character.isdigit())
    if len(digits) < 7 or len(digits) > 15:
        raise IntakeStoreError("Phone number must contain between 7 and 15 digits.")
    if len(digits) == 10:
        display = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    elif len(digits) == 7:
        display = f"{digits[:3]}-{digits[3:]}"
    else:
        display = f"+{digits}"
    return display, digits


def _owner_query(db: Session, auth: AuthContext) -> Select[tuple[IntakeRequest]]:
    return select(IntakeRequest).where(IntakeRequest.shop_id == effective_shop_id(db, auth))


def _get_intake_request(db: Session, auth: AuthContext, intake_request_id: int) -> IntakeRequest:
    intake_request = db.scalar(_owner_query(db, auth).where(IntakeRequest.id == intake_request_id))
    if intake_request is None:
        raise IntakeRequestNotFoundError("Intake request not found.")
    return intake_request


def _to_read(intake_request: IntakeRequest) -> IntakeRequestRead:
    return IntakeRequestRead(
        id=intake_request.id,
        customer_name=intake_request.customer_name,
        phone=intake_request.phone,
        email=intake_request.email,
        vehicle_description=intake_request.vehicle_description,
        complaint=intake_request.complaint,
        source=intake_request.source,  # type: ignore[arg-type]
        status=intake_request.status,  # type: ignore[arg-type]
        notes=intake_request.notes,
        converted_customer_id=intake_request.converted_customer_id,
        converted_vehicle_id=intake_request.converted_vehicle_id,
        created_at=ensure_utc(intake_request.created_at),
        updated_at=ensure_utc(intake_request.updated_at),
    )


def create_intake_request(
    *, db: Session, auth: AuthContext, payload: IntakeRequestCreate
) -> IntakeRequestRead:
    email = normalize_email(payload.email)
    phone = normalize_phone(payload.phone)
    intake_request = IntakeRequest(
        owner_user_id=effective_shop_owner_id(db, auth),
        shop_id=resolve_shop_id(db, auth),
        customer_name=payload.customer_name,
        phone=phone[0] if phone else None,
        phone_normalized=phone[1] if phone else None,
        email=email,
        email_normalized=email,
        vehicle_description=payload.vehicle_description,
        complaint=payload.complaint,
        source=payload.source.value,
        status="new",
        notes=payload.notes,
    )
    db.add(intake_request)
    db.commit()
    db.refresh(intake_request)
    return _to_read(intake_request)


def get_intake_request(
    *, db: Session, auth: AuthContext, intake_request_id: int
) -> IntakeRequestRead:
    return _to_read(_get_intake_request(db, auth, intake_request_id))


def update_intake_request(
    *,
    db: Session,
    auth: AuthContext,
    intake_request_id: int,
    payload: IntakeRequestUpdate,
) -> IntakeRequestRead:
    intake_request = _get_intake_request(db, auth, intake_request_id)
    fields_set = payload.model_fields_set
    if "customer_name" in fields_set and payload.customer_name is not None:
        intake_request.customer_name = payload.customer_name
    if "phone" in fields_set:
        phone = normalize_phone(payload.phone)
        intake_request.phone = phone[0] if phone else None
        intake_request.phone_normalized = phone[1] if phone else None
    if "email" in fields_set:
        email = normalize_email(payload.email)
        intake_request.email = email
        intake_request.email_normalized = email
    if "vehicle_description" in fields_set:
        intake_request.vehicle_description = payload.vehicle_description
    if "complaint" in fields_set and payload.complaint is not None:
        intake_request.complaint = payload.complaint
    if "source" in fields_set and payload.source is not None:
        intake_request.source = payload.source.value
    if "status" in fields_set and payload.status is not None:
        if intake_request.status == "converted" and payload.status.value != "converted":
            raise IntakeConflictError(
                "A converted intake request's status cannot be changed by hand."
            )
        intake_request.status = payload.status.value
    if "notes" in fields_set:
        intake_request.notes = payload.notes
    db.add(intake_request)
    db.commit()
    db.refresh(intake_request)
    return _to_read(intake_request)


def list_intake_requests(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    status_filter: str | None,
    search: str | None,
) -> IntakeRequestListResponse:
    if page_size > settings.customers_max_page_size:
        raise IntakeStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise IntakeStoreError("Page must be 1 or greater.")

    query = _owner_query(db, auth)
    if status_filter:
        query = query.where(IntakeRequest.status == status_filter)
    if search:
        lowered_tokens = [token for token in search.strip().lower().split() if token]
        for token in lowered_tokens:
            clause = or_(
                func.lower(IntakeRequest.customer_name).contains(token),
                func.lower(func.coalesce(IntakeRequest.vehicle_description, "")).contains(token),
                func.lower(IntakeRequest.complaint).contains(token),
            )
            query = query.where(clause)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    intake_requests = db.scalars(
        query.order_by(IntakeRequest.updated_at.desc(), IntakeRequest.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return IntakeRequestListResponse(
        items=[_to_read(intake_request) for intake_request in intake_requests],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(intake_requests) < total,
    )


def _split_customer_name(customer_name: str) -> tuple[str, str | None]:
    parts = customer_name.strip().split(maxsplit=1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], None


def convert_intake_request(
    *,
    db: Session,
    auth: AuthContext,
    intake_request_id: int,
    payload: IntakeRequestConvertRequest,
) -> IntakeRequestConvertResponse:
    intake_request = _get_intake_request(db, auth, intake_request_id)

    # Lock the row before checking status, then reload it with
    # populate_existing so a concurrent double-conversion request (two
    # requests that both read the row before either commits) serializes on
    # the lock rather than both passing the status check -- same pattern as
    # `purchase_order_store.py`'s receive-line-item lock and
    # `part_allocation_store.py`'s allocate/use/return locks.
    db.execute(
        select(IntakeRequest.id).where(IntakeRequest.id == intake_request.id).with_for_update()
    )
    db.refresh(intake_request)
    if intake_request.status == "converted":
        raise IntakeConflictError("This intake request has already been converted.")

    first_name, last_name = _split_customer_name(intake_request.customer_name)
    customer = create_customer(
        db=db,
        auth=auth,
        payload=CustomerCreate(
            first_name=first_name,
            last_name=last_name,
            email=intake_request.email,
            phone=intake_request.phone,
        ),
    )

    vehicle = None
    if payload.vehicle_make and payload.vehicle_model:
        vehicle = create_vehicle(
            db=db,
            auth=auth,
            customer_id=customer.id,
            payload=VehicleCreate(
                year=payload.vehicle_year,
                make=payload.vehicle_make,
                model=payload.vehicle_model,
                vin=payload.vehicle_vin,
            ),
        )

    intake_request.status = "converted"
    intake_request.converted_customer_id = customer.id
    intake_request.converted_vehicle_id = vehicle.id if vehicle else None
    db.add(intake_request)
    db.commit()
    db.refresh(intake_request)
    return IntakeRequestConvertResponse(
        intake_request=_to_read(intake_request),
        customer=customer,
        vehicle=vehicle,
    )
