from __future__ import annotations

import re

from sqlalchemy import Select, String, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id, effective_shop_owner_id, ensure_utc
from app.config import Settings
from app.customer_store import display_name as customer_display_name
from app.customer_store import get_customer_model
from app.db_models import Vehicle
from app.models import (
    VehicleArchiveResponse,
    VehicleCreate,
    VehicleListResponse,
    VehicleRead,
    VehicleUpdate,
)
from app.shop_store import resolve_shop_id

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


class VehicleStoreError(ValueError):
    pass


class VehicleNotFoundError(VehicleStoreError):
    pass


def normalize_vin(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(value.upper().split())
    if not normalized:
        return None
    if len(normalized) != 17:
        raise VehicleStoreError("VIN must be exactly 17 characters.")
    if not _VIN_RE.fullmatch(normalized):
        raise VehicleStoreError(
            "VIN must contain only valid letters and digits and cannot contain I, O, or Q."
        )
    return normalized


def normalize_license_plate(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    display = " ".join(value.strip().upper().split())
    if not display:
        return None, None
    normalized = "".join(character for character in display if character.isalnum())
    return display, normalized or None


def normalize_vehicle_fields(payload: VehicleCreate | VehicleUpdate) -> dict[str, object]:
    license_plate, license_plate_normalized = normalize_license_plate(payload.license_plate)
    return {
        "vin": normalize_vin(payload.vin),
        "year": payload.year,
        "make": payload.make,
        "model": payload.model,
        "trim": payload.trim,
        "engine": payload.engine,
        "drivetrain": payload.drivetrain,
        "transmission": payload.transmission,
        "license_plate": license_plate,
        "license_plate_state": payload.license_plate_state.upper()
        if payload.license_plate_state
        else None,
        "license_plate_normalized": license_plate_normalized,
        "color": payload.color,
        "current_mileage": payload.current_mileage,
        "fleet_unit_number": payload.fleet_unit_number,
        "internal_notes": payload.internal_notes,
    }


def validate_required_identity(*, make: str | None, model: str | None) -> None:
    if make and model:
        return
    raise VehicleStoreError("Vehicle make and model are required.")


def vehicle_display_name(vehicle: Vehicle) -> str:
    label = " ".join(
        part
        for part in [str(vehicle.year) if vehicle.year else None, vehicle.make, vehicle.model]
        if part
    )
    if vehicle.trim:
        label = f"{label} {vehicle.trim}".strip()
    return label or vehicle.vin or vehicle.license_plate or "Unnamed vehicle"


def _to_read(vehicle: Vehicle) -> VehicleRead:
    return VehicleRead(
        id=vehicle.id,
        customer_id=vehicle.customer_id,
        customer_display_name=customer_display_name(vehicle.customer) if vehicle.customer else None,
        vin=vehicle.vin,
        year=vehicle.year,
        make=vehicle.make,
        model=vehicle.model,
        trim=vehicle.trim,
        engine=vehicle.engine,
        drivetrain=vehicle.drivetrain,
        transmission=vehicle.transmission,
        license_plate=vehicle.license_plate,
        license_plate_state=vehicle.license_plate_state,
        color=vehicle.color,
        current_mileage=vehicle.current_mileage,
        fleet_unit_number=vehicle.fleet_unit_number,
        internal_notes=vehicle.internal_notes,
        display_name=vehicle_display_name(vehicle),
        is_archived=vehicle.is_archived,
        created_at=ensure_utc(vehicle.created_at),
        updated_at=ensure_utc(vehicle.updated_at),
    )


def _owner_query(db: Session, auth: AuthContext) -> Select[tuple[Vehicle]]:
    return select(Vehicle).where(Vehicle.shop_id == effective_shop_id(db, auth))


def _get_vehicle(db: Session, auth: AuthContext, vehicle_id: int) -> Vehicle:
    vehicle = db.scalar(_owner_query(db, auth).where(Vehicle.id == vehicle_id))
    if vehicle is None:
        raise VehicleNotFoundError("Vehicle not found.")
    return vehicle


def get_vehicle_model(*, db: Session, auth: AuthContext, vehicle_id: int) -> Vehicle:
    return _get_vehicle(db, auth, vehicle_id)


def _ensure_unique_active_vin(
    db: Session,
    auth: AuthContext,
    vin: str | None,
    *,
    ignore_vehicle_id: int | None = None,
) -> None:
    if vin is None:
        return
    query = _owner_query(db, auth).where(Vehicle.vin == vin).where(Vehicle.is_archived.is_(False))
    if ignore_vehicle_id is not None:
        query = query.where(Vehicle.id != ignore_vehicle_id)
    if db.scalar(query) is not None:
        raise VehicleStoreError("An active vehicle with this VIN already exists.")


def create_vehicle(
    *,
    db: Session,
    auth: AuthContext,
    customer_id: int,
    payload: VehicleCreate,
    commit: bool = True,
) -> VehicleRead:
    customer = get_customer_model(db=db, auth=auth, customer_id=customer_id)
    normalized = normalize_vehicle_fields(payload)
    validate_required_identity(make=payload.make, model=payload.model)
    vin = normalize_vin(payload.vin)
    _ensure_unique_active_vin(db, auth, vin)
    vehicle = Vehicle(
        owner_user_id=effective_shop_owner_id(db, auth),
        shop_id=resolve_shop_id(db, auth),
        customer_id=customer.id,
        **normalized,
    )
    db.add(vehicle)
    # `commit=False` lets a caller compose this create atomically with a
    # customer create (see intake conversion) so a duplicate-VIN rejection here
    # rolls back the whole transaction and never leaves an orphan customer.
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(vehicle)
    return _to_read(vehicle)


def get_vehicle(*, db: Session, auth: AuthContext, vehicle_id: int) -> VehicleRead:
    return _to_read(_get_vehicle(db, auth, vehicle_id))


def update_vehicle(
    *,
    db: Session,
    auth: AuthContext,
    vehicle_id: int,
    payload: VehicleUpdate,
) -> VehicleRead:
    vehicle = _get_vehicle(db, auth, vehicle_id)
    normalized = normalize_vehicle_fields(payload)
    for field in payload.model_fields_set:
        setattr(vehicle, field, normalized[field])
        if field == "license_plate":
            vehicle.license_plate_normalized = normalized["license_plate_normalized"]  # type: ignore[assignment]
        if field == "license_plate_state":
            vehicle.license_plate_state = normalized["license_plate_state"]  # type: ignore[assignment]
    validate_required_identity(make=vehicle.make, model=vehicle.model)
    _ensure_unique_active_vin(db, auth, vehicle.vin, ignore_vehicle_id=vehicle.id)
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return _to_read(vehicle)


def archive_vehicle(
    *,
    db: Session,
    auth: AuthContext,
    vehicle_id: int,
) -> VehicleArchiveResponse:
    vehicle = _get_vehicle(db, auth, vehicle_id)
    vehicle.is_archived = True
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return VehicleArchiveResponse(vehicle=_to_read(vehicle))


def list_vehicles(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    archived: bool,
    search: str | None,
    customer_id: int | None = None,
) -> VehicleListResponse:
    if page_size > settings.vehicles_max_page_size:
        raise VehicleStoreError(
            f"Page size exceeds the maximum of {settings.vehicles_max_page_size}."
        )
    if page < 1:
        raise VehicleStoreError("Page must be 1 or greater.")
    if customer_id is not None:
        get_customer_model(db=db, auth=auth, customer_id=customer_id)

    query = _owner_query(db, auth).where(Vehicle.is_archived == archived)
    if customer_id is not None:
        query = query.where(Vehicle.customer_id == customer_id)
    if search:
        lowered_tokens = [token for token in search.strip().lower().split() if token]
        if lowered_tokens:
            token_clauses = []
            for token in lowered_tokens:
                uppercase_token = token.upper()
                normalized_plate = "".join(
                    character for character in uppercase_token if character.isalnum()
                )
                clause = or_(
                    func.coalesce(Vehicle.vin, "").contains(uppercase_token),
                    func.lower(func.coalesce(Vehicle.make, "")).contains(token),
                    func.lower(func.coalesce(Vehicle.model, "")).contains(token),
                    func.lower(func.coalesce(Vehicle.trim, "")).contains(token),
                )
                if normalized_plate:
                    clause = or_(
                        clause,
                        func.coalesce(Vehicle.license_plate_normalized, "").contains(
                            normalized_plate
                        ),
                    )
                if token.isdigit():
                    clause = or_(
                        clause,
                        cast(func.coalesce(Vehicle.year, 0), String).contains(token),
                    )
                token_clauses.append(clause)
            query = query.where(and_(*token_clauses))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    vehicles = db.scalars(
        query.order_by(Vehicle.updated_at.desc(), Vehicle.id.desc()).offset(offset).limit(page_size)
    ).all()
    return VehicleListResponse(
        items=[_to_read(vehicle) for vehicle in vehicles],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(vehicles) < total,
    )
