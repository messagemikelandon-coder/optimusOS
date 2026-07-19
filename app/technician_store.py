from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TypedDict

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import (
    AuthContext,
    effective_shop_id,
    effective_shop_owner_id,
    ensure_utc,
    hash_password,
    normalize_username,
)
from app.config import Settings
from app.db_models import (
    AuthSession,
    PasswordResetToken,
    ShopMembership,
    ShopSubscription,
    Technician,
    TechnicianTimeEntry,
    UserAccount,
    WorkOrder,
)
from app.models import (
    TechnicianArchiveResponse,
    TechnicianClockResponse,
    TechnicianCreate,
    TechnicianListResponse,
    TechnicianMeResponse,
    TechnicianProvisionLoginRequest,
    TechnicianProvisionLoginResponse,
    TechnicianRead,
    TechnicianSelfRead,
    TechnicianTimeEntryRead,
    TechnicianUpdate,
)
from app.shop_store import resolve_shop_id

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class TechnicianStoreError(ValueError):
    pass


class TechnicianNotFoundError(TechnicianStoreError):
    pass


class TechnicianConflictError(TechnicianStoreError):
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
        raise TechnicianStoreError("Email address is invalid.")
    return normalized


def normalize_phone(value: str | None) -> NormalizedPhone | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    digits = "".join(character for character in stripped if character.isdigit())
    if len(digits) < 7 or len(digits) > 15:
        raise TechnicianStoreError("Phone number must contain between 7 and 15 digits.")
    if len(digits) == 7:
        display = f"{digits[:3]}-{digits[3:]}"
    elif len(digits) == 10:
        display = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits.startswith("1"):
        display = f"+1 {digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    else:
        display = f"+{digits}"
    return NormalizedPhone(display=display, normalized=digits)


def _decimal_money(value: float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        normalized = Decimal(str(value))
    except InvalidOperation as exc:
        raise TechnicianStoreError("Hourly cost is invalid.") from exc
    if not normalized.is_finite() or normalized < 0:
        raise TechnicianStoreError("Hourly cost must be zero or greater.")
    return normalized.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_technician_fields(payload: TechnicianCreate | TechnicianUpdate) -> dict[str, object]:
    email = normalize_email(payload.email)
    phone = normalize_phone(payload.phone)
    return {
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "phone": phone.display if phone else None,
        "phone_normalized": phone.normalized if phone else None,
        "email": email,
        "email_normalized": email,
        "employment_status": payload.employment_status,
        "job_title": payload.job_title,
        "hire_date": payload.hire_date,
        "hourly_cost": _decimal_money(payload.hourly_cost),
        "certifications": payload.certifications,
        "certification_expiration": payload.certification_expiration,
        "specialties": payload.specialties,
        "driver_license_valid": payload.driver_license_valid,
        "insurance_verified": payload.insurance_verified,
        "normal_availability": payload.normal_availability,
        "safety_notes": payload.safety_notes,
    }


def display_name(technician: Technician) -> str:
    name = " ".join(part for part in [technician.first_name, technician.last_name] if part)
    return name or "Unnamed technician"


class _TechnicianComputedFields(TypedDict):
    id: int
    first_name: str | None
    last_name: str | None
    phone: str | None
    email: str | None
    employment_status: str | None
    job_title: str | None
    hire_date: date | None
    certifications: str | None
    certification_expiration: date | None
    specialties: str | None
    driver_license_valid: bool | None
    insurance_verified: bool | None
    normal_availability: str | None
    safety_notes: str | None
    display_name: str
    is_archived: bool
    has_login: bool
    is_clocked_in: bool
    comeback_count: int
    created_at: datetime
    updated_at: datetime


def _technician_computed_fields(db: Session, technician: Technician) -> _TechnicianComputedFields:
    open_entries = (
        db.scalar(
            select(func.count())
            .select_from(TechnicianTimeEntry)
            .where(
                TechnicianTimeEntry.technician_id == technician.id,
                TechnicianTimeEntry.shop_id == technician.shop_id,
                TechnicianTimeEntry.clock_out_at.is_(None),
            )
        )
        or 0
    )
    comeback_count = (
        db.scalar(
            select(func.count())
            .select_from(WorkOrder)
            .where(
                WorkOrder.assigned_technician_id == technician.id,
                WorkOrder.shop_id == technician.shop_id,
                WorkOrder.is_comeback.is_(True),
            )
        )
        or 0
    )
    return {
        "id": technician.id,
        "first_name": technician.first_name,
        "last_name": technician.last_name,
        "phone": technician.phone,
        "email": technician.email,
        "employment_status": technician.employment_status,
        "job_title": technician.job_title,
        "hire_date": technician.hire_date,
        "certifications": technician.certifications,
        "certification_expiration": technician.certification_expiration,
        "specialties": technician.specialties,
        "driver_license_valid": technician.driver_license_valid,
        "insurance_verified": technician.insurance_verified,
        "normal_availability": technician.normal_availability,
        "safety_notes": technician.safety_notes,
        "display_name": display_name(technician),
        "is_archived": technician.is_archived,
        "has_login": technician.user_account_id is not None,
        "is_clocked_in": open_entries > 0,
        "comeback_count": comeback_count,
        "created_at": ensure_utc(technician.created_at),
        "updated_at": ensure_utc(technician.updated_at),
    }


def _to_read(db: Session, technician: Technician) -> TechnicianRead:
    return TechnicianRead(
        **_technician_computed_fields(db, technician),
        hourly_cost=float(technician.hourly_cost) if technician.hourly_cost is not None else None,
    )


def _to_self_read(db: Session, technician: Technician) -> TechnicianSelfRead:
    """Owner-visible-only fields (like `hourly_cost`) are deliberately
    excluded here -- see `TechnicianSelfRead`'s docstring."""
    return TechnicianSelfRead(**_technician_computed_fields(db, technician))


def _entry_to_read(entry: TechnicianTimeEntry) -> TechnicianTimeEntryRead:
    duration_minutes = None
    if entry.clock_out_at is not None:
        duration_minutes = int((entry.clock_out_at - entry.clock_in_at).total_seconds() // 60)
    return TechnicianTimeEntryRead(
        id=entry.id,
        clock_in_at=ensure_utc(entry.clock_in_at),
        clock_out_at=ensure_utc(entry.clock_out_at) if entry.clock_out_at else None,
        duration_minutes=duration_minutes,
    )


def _owner_query(db: Session, auth: AuthContext) -> Select[tuple[Technician]]:
    return select(Technician).where(Technician.shop_id == effective_shop_id(db, auth))


def _get_technician(
    db: Session, auth: AuthContext, technician_id: int, *, for_update: bool = False
) -> Technician:
    query = _owner_query(db, auth).where(Technician.id == technician_id)
    if for_update:
        query = query.with_for_update()
    technician = db.scalar(query)
    if technician is None:
        raise TechnicianNotFoundError("Technician not found.")
    return technician


def get_technician_model(*, db: Session, auth: AuthContext, technician_id: int) -> Technician:
    return _get_technician(db, auth, technician_id)


def get_technician_for_user(db: Session, auth: AuthContext) -> Technician | None:
    return db.scalar(
        select(Technician).where(
            Technician.user_account_id == auth.user.id,
            Technician.shop_id == effective_shop_id(db, auth),
            Technician.is_archived.is_(False),
        )
    )


def enforce_technician_seat_limit(db: Session, shop_id: int) -> None:
    """/goal Phase 7: a shop's subscription tier caps how many non-archived
    Technician profiles it may hold. Locks the subscription row first so two
    concurrent creates at exactly the seat limit cannot both pass this check
    -- mirrors the row-lock pattern already used for occurrence-recording in
    `app/workflow_gap_store.py`. Public (not `_`-prefixed): also called from
    `app/account_security_store.py::accept_invitation`, the other code path
    that can create a brand-new `Technician` row (a security-review finding
    -- invitation acceptance previously bypassed this check entirely)."""
    subscription = db.scalar(
        select(ShopSubscription).where(ShopSubscription.shop_id == shop_id).with_for_update()
    )
    if subscription is None or subscription.seat_limit is None:
        return
    active_seats = (
        db.scalar(
            select(func.count())
            .select_from(Technician)
            .where(Technician.shop_id == shop_id, Technician.is_archived.is_(False))
        )
        or 0
    )
    if active_seats >= subscription.seat_limit:
        raise TechnicianConflictError(
            f"This shop's subscription allows {subscription.seat_limit} technician seat(s); "
            "archive a technician or upgrade the plan before adding another."
        )


def create_technician(
    *,
    db: Session,
    auth: AuthContext,
    payload: TechnicianCreate,
) -> TechnicianRead:
    shop_id = resolve_shop_id(db, auth)
    enforce_technician_seat_limit(db, shop_id)
    normalized = normalize_technician_fields(payload)
    technician = Technician(
        owner_user_id=effective_shop_owner_id(db, auth),
        shop_id=shop_id,
        **normalized,
    )
    db.add(technician)
    db.commit()
    db.refresh(technician)
    return _to_read(db, technician)


def get_technician(*, db: Session, auth: AuthContext, technician_id: int) -> TechnicianRead:
    return _to_read(db, _get_technician(db, auth, technician_id))


def update_technician(
    *,
    db: Session,
    auth: AuthContext,
    technician_id: int,
    payload: TechnicianUpdate,
) -> TechnicianRead:
    technician = _get_technician(db, auth, technician_id)
    normalized = normalize_technician_fields(payload)
    field_map = {
        "first_name": ["first_name"],
        "last_name": ["last_name"],
        "phone": ["phone", "phone_normalized"],
        "email": ["email", "email_normalized"],
        "employment_status": ["employment_status"],
        "job_title": ["job_title"],
        "hire_date": ["hire_date"],
        "hourly_cost": ["hourly_cost"],
        "certifications": ["certifications"],
        "certification_expiration": ["certification_expiration"],
        "specialties": ["specialties"],
        "driver_license_valid": ["driver_license_valid"],
        "insurance_verified": ["insurance_verified"],
        "normal_availability": ["normal_availability"],
        "safety_notes": ["safety_notes"],
    }
    for payload_field, target_fields in field_map.items():
        if payload_field not in payload.model_fields_set:
            continue
        for target_field in target_fields:
            setattr(technician, target_field, normalized[target_field])
    db.add(technician)
    db.commit()
    db.refresh(technician)
    return _to_read(db, technician)


def archive_technician(
    *,
    db: Session,
    auth: AuthContext,
    technician_id: int,
) -> TechnicianArchiveResponse:
    technician = _get_technician(db, auth, technician_id)
    if technician.user_account_id is not None:
        linked = db.execute(
            select(UserAccount, ShopMembership)
            .join(ShopMembership, ShopMembership.user_account_id == UserAccount.id)
            .where(
                UserAccount.id == technician.user_account_id,
                UserAccount.role == "technician",
                ShopMembership.user_account_id == technician.user_account_id,
                ShopMembership.shop_id == technician.shop_id,
                ShopMembership.role == "technician",
                ShopMembership.is_active.is_(True),
            )
        ).one_or_none()
        if linked is None:
            raise TechnicianStoreError(
                "This technician's login is not valid for the same active Shop membership."
            )
        user, membership = linked
        user.is_active = False
        user.account_status = "disabled"
        membership.is_active = False
        db.add(user)
        db.add(membership)
        sessions = db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == technician.user_account_id,
                AuthSession.revoked_at.is_(None),
            )
        ).all()
        revoked_at = datetime.now(UTC)
        for session in sessions:
            session.revoked_at = revoked_at
            db.add(session)
        db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_account_id == technician.user_account_id,
                PasswordResetToken.status == "active",
            )
            .values(status="revoked", revoked_at=revoked_at)
        )
    technician.is_archived = True
    db.add(technician)
    db.commit()
    db.refresh(technician)
    return TechnicianArchiveResponse(technician=_to_read(db, technician))


def list_technicians(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    archived: bool,
    search: str | None,
) -> TechnicianListResponse:
    if page_size > settings.customers_max_page_size:
        raise TechnicianStoreError(
            f"Page size exceeds the maximum of {settings.customers_max_page_size}."
        )
    if page < 1:
        raise TechnicianStoreError("Page must be 1 or greater.")

    query = _owner_query(db, auth).where(Technician.is_archived == archived)
    if search:
        lowered_tokens = [token for token in search.strip().lower().split() if token]
        if lowered_tokens:
            token_clauses = []
            for token in lowered_tokens:
                clause = or_(
                    func.lower(func.coalesce(Technician.first_name, "")).contains(token),
                    func.lower(func.coalesce(Technician.last_name, "")).contains(token),
                    func.lower(func.coalesce(Technician.email_normalized, "")).contains(token),
                    func.lower(func.coalesce(Technician.job_title, "")).contains(token),
                )
                digits = "".join(character for character in token if character.isdigit())
                if digits:
                    clause = or_(
                        clause, func.coalesce(Technician.phone_normalized, "").contains(digits)
                    )
                token_clauses.append(clause)
            for clause in token_clauses:
                query = query.where(clause)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    technicians = db.scalars(
        query.order_by(Technician.updated_at.desc(), Technician.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return TechnicianListResponse(
        items=[_to_read(db, technician) for technician in technicians],
        page=page,
        page_size=page_size,
        total=total,
        has_more=offset + len(technicians) < total,
    )


def provision_login(
    *,
    db: Session,
    auth: AuthContext,
    technician_id: int,
    payload: TechnicianProvisionLoginRequest,
) -> TechnicianProvisionLoginResponse:
    if auth.user.role not in {"owner", "manager"}:
        raise TechnicianStoreError("Only shop owners and managers can provision logins.")
    technician = _get_technician(db, auth, technician_id, for_update=True)
    if technician.user_account_id is not None:
        raise TechnicianConflictError("This technician already has a login.")

    owner_id = effective_shop_owner_id(db, auth)
    # Security-review-mandated check (Phase 5.6 sub-phase 1 finding): a
    # technician's shop_owner_id must reference a real owner row, never
    # another technician or a nonexistent id, or effective_shop_owner_id() would
    # start scoping chained/self-referencing technicians unpredictably.
    owner = db.get(UserAccount, owner_id)
    if owner is None or owner.role != "owner":
        raise TechnicianStoreError(
            "Technician logins can only be provisioned under a valid shop owner."
        )

    normalized_username = normalize_username(payload.username)
    existing_user = db.scalar(
        select(UserAccount).where(UserAccount.username == normalized_username)
    )
    if existing_user is not None:
        raise TechnicianConflictError("That username is already taken.")

    user = UserAccount(
        username=normalized_username,
        display_name=display_name(technician),
        role="technician",
        shop_owner_id=owner_id,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
        db.add(
            ShopMembership(
                shop_id=resolve_shop_id(db, auth),
                user_account_id=user.id,
                role="technician",
            )
        )
        db.flush()
    except IntegrityError:
        db.rollback()
        raise TechnicianConflictError("That username is already taken.") from None
    technician.user_account_id = user.id
    db.add(technician)
    db.commit()
    db.refresh(technician)
    return TechnicianProvisionLoginResponse(
        technician=_to_read(db, technician), username=normalized_username
    )


def _require_own_technician(db: Session, auth: AuthContext) -> Technician:
    technician = get_technician_for_user(db, auth)
    if technician is None:
        raise TechnicianNotFoundError("No technician profile is linked to this login.")
    return technician


def clock_in(*, db: Session, auth: AuthContext) -> TechnicianClockResponse:
    technician = _require_own_technician(db, auth)
    open_entry = db.scalar(
        select(TechnicianTimeEntry).where(
            TechnicianTimeEntry.technician_id == technician.id,
            TechnicianTimeEntry.shop_id == technician.shop_id,
            TechnicianTimeEntry.clock_out_at.is_(None),
        )
    )
    if open_entry is not None:
        raise TechnicianConflictError("Already clocked in.")
    entry = TechnicianTimeEntry(
        technician_id=technician.id,
        owner_user_id=technician.owner_user_id,
        shop_id=technician.shop_id,
        clock_in_at=datetime.now(UTC),
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise TechnicianConflictError("Already clocked in.") from None
    db.refresh(entry)
    return TechnicianClockResponse(is_clocked_in=True, entry=_entry_to_read(entry))


def clock_out(*, db: Session, auth: AuthContext) -> TechnicianClockResponse:
    technician = _require_own_technician(db, auth)
    entry = db.scalar(
        select(TechnicianTimeEntry).where(
            TechnicianTimeEntry.technician_id == technician.id,
            TechnicianTimeEntry.shop_id == technician.shop_id,
            TechnicianTimeEntry.clock_out_at.is_(None),
        )
    )
    if entry is None:
        raise TechnicianConflictError("Not currently clocked in.")
    entry.clock_out_at = datetime.now(UTC)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return TechnicianClockResponse(is_clocked_in=False, entry=_entry_to_read(entry))


def get_my_technician_profile(*, db: Session, auth: AuthContext) -> TechnicianMeResponse:
    technician = _require_own_technician(db, auth)
    recent_entries = db.scalars(
        select(TechnicianTimeEntry)
        .where(
            TechnicianTimeEntry.technician_id == technician.id,
            TechnicianTimeEntry.shop_id == technician.shop_id,
        )
        .order_by(TechnicianTimeEntry.clock_in_at.desc())
        .limit(10)
    ).all()
    assigned_ids = db.scalars(
        select(WorkOrder.id).where(
            WorkOrder.assigned_technician_id == technician.id,
            WorkOrder.shop_id == technician.shop_id,
            WorkOrder.status.notin_(["completed", "cancelled"]),
        )
    ).all()
    return TechnicianMeResponse(
        technician=_to_self_read(db, technician),
        recent_time_entries=[_entry_to_read(entry) for entry in recent_entries],
        assigned_work_order_ids=list(assigned_ids),
    )
