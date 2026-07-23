from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

# Phase 2B runtime-observability enums reused as response-model field types.
# app.runtime_monitor is a leaf (imports only app.net / app.storage_monitor /
# redis), so this import introduces no cycle.
from app.runtime_monitor import (
    DependencyStatus,
    QueueStatus,
    WorkerHeartbeatStatus,
)

# Phase 2A storage-observability enums/category type reused as response-model
# field types (keeps the OpenAPI schema and the collector in one vocabulary).
# app.storage_monitor is a stdlib-only leaf, so this import introduces no cycle.
from app.storage_monitor import (
    DiskThresholdStatus,
    DockerAvailability,
    DockerCategory,
    Freshness,
)

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# A separate type, not `NonBlank = Field(min_length=8, ...)`: that combination
# silently never enforced 8 characters anywhere it was used (AuthLoginRequest,
# TechnicianProvisionLoginRequest) -- Pydantic merges `Field()`'s constraint
# metadata with `NonBlank`'s own baked-in `StringConstraints(min_length=1)`,
# and the later item in the merged metadata list wins, so only `min_length=1`
# ever actually applied. Found while adding /goal Phase 4 signup's own
# password field and confirmed via a direct validation test before assuming
# it was real. `strip_whitespace=True` is preserved exactly as `NonBlank` already
# applied it, so this does not change what an existing account's hashed
# password was computed from.
Password = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=256)]


class Coordinates(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)


class LocationInput(BaseModel):
    coordinates: Coordinates | None = None
    postal_code: str | None = Field(default=None, pattern=r"^\d{5}(?:-\d{4})?$")
    city: str | None = Field(default=None, min_length=1, max_length=100)
    region: str | None = Field(default=None, min_length=1, max_length=100)
    country: str = Field(default="US", pattern=r"^[A-Z]{2}$")
    timezone: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_location(self) -> LocationInput:
        if not self.coordinates and not self.postal_code and not (self.city and self.region):
            raise ValueError("Provide coordinates, a ZIP code, or city and region.")
        return self


class ResolvedLocation(BaseModel):
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str = "US"
    timezone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    source: Literal["user", "census_coordinates", "partial"] = "user"

    def search_label(self) -> str:
        pieces = [self.city, self.region, self.postal_code, self.country]
        label = ", ".join(piece for piece in pieces if piece)
        if label:
            return label
        if self.latitude is not None and self.longitude is not None:
            return f"{self.latitude:.4f}, {self.longitude:.4f}"
        return self.country


class VehicleInput(BaseModel):
    vin: str | None = Field(default=None, min_length=11, max_length=17)
    year: int | None = Field(default=None, ge=1900, le=2100)
    make: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=80)
    trim: str | None = Field(default=None, min_length=1, max_length=80)
    engine: str | None = Field(default=None, min_length=1, max_length=120)
    drivetrain: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("vin")
    @classmethod
    def normalize_vin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = "".join(value.upper().split())
        if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{11,17}", cleaned):
            raise ValueError(
                "VIN must contain 11-17 valid letters and digits and cannot contain I, O, or Q."
            )
        return cleaned

    @model_validator(mode="after")
    def require_vin_or_vehicle(self) -> VehicleInput:
        if not self.vin and not (self.year and self.make and self.model):
            raise ValueError("Provide a VIN or year, make, and model.")
        return self

    def display_name(self) -> str:
        parts = [
            str(self.year) if self.year else None,
            self.make,
            self.model,
            self.trim,
            self.engine,
        ]
        return " ".join(part for part in parts if part) or self.vin or "Unknown vehicle"


class DecodedVehicle(BaseModel):
    vin: str | None = None
    year: int | None = None
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    engine: str | None = None
    drivetrain: str | None = None
    body_class: str | None = None
    error_code: str | None = None
    error_text: str | None = None

    def display_name(self) -> str:
        parts = [
            str(self.year) if self.year else None,
            self.make,
            self.model,
            self.trim,
            self.engine,
        ]
        return " ".join(part for part in parts if part) or self.vin or "Unknown vehicle"


class VinDecodeStatus(StrEnum):
    """Outcome of a standalone vehicle-intake VIN decode.

    ``decoded`` -- year, make, and model were all resolved.
    ``partial`` -- some identity fields resolved, but not the full year/make/model.
    ``unavailable`` -- the decode service could not be reached or returned nothing;
    the caller should fall back to manual entry. This is the safe-failure state:
    the endpoint never surfaces a 5xx for an unreachable upstream, and never
    presents an un-decoded VIN as if it were a confirmed vehicle.
    """

    DECODED = "decoded"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class VinDecodeRequest(BaseModel):
    """A vehicle-first VIN decode request. No customer is required -- the shop can
    identify a vehicle before any customer record exists."""

    vin: str = Field(min_length=17, max_length=17)

    @field_validator("vin")
    @classmethod
    def normalize_vin(cls, value: str) -> str:
        cleaned = "".join(value.upper().split())
        if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", cleaned):
            raise ValueError(
                "VIN must be exactly 17 valid letters and digits and cannot contain I, O, or Q."
            )
        return cleaned


class VinDecodeResponse(BaseModel):
    """Safe-failure result of a standalone VIN decode. ``decoded`` is populated on
    ``decoded``/``partial`` and is ``None`` on ``unavailable``. ``message`` is a
    short, human-facing explanation suitable for a toast."""

    status: VinDecodeStatus
    message: str
    decoded: DecodedVehicle | None = None


class Availability(StrEnum):
    CONFIRMED_IN_STOCK = "confirmed_in_stock"
    LIMITED = "limited"
    UNKNOWN = "unknown"
    OUT_OF_STOCK = "out_of_stock"
    ONLINE_ONLY = "online_only"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Citation(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    supports: str | None = Field(default=None, max_length=300)


class LaborResearch(BaseModel):
    book_hours: float = Field(ge=0, le=200)
    practical_hours_low: float = Field(ge=0, le=300)
    practical_hours_high: float = Field(ge=0, le=300)
    confidence: Confidence = Confidence.LOW
    basis: str = Field(min_length=1, max_length=1500)
    special_tools: list[str] = Field(default_factory=list, max_length=30)
    risk_flags: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_range(self) -> LaborResearch:
        if self.practical_hours_low > self.practical_hours_high:
            raise ValueError("practical_hours_low cannot exceed practical_hours_high")
        return self


class PartOption(BaseModel):
    retailer: str = Field(min_length=1, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    part_number: str | None = Field(default=None, max_length=100)
    unit_price: float | None = Field(default=None, gt=0, le=100_000)
    availability: Availability = Availability.UNKNOWN
    store_name: str | None = Field(default=None, max_length=200)
    store_distance_miles: float | None = Field(default=None, ge=0, le=1000)
    url: HttpUrl
    fitment_notes: str | None = Field(default=None, max_length=1000)
    confidence: Confidence = Confidence.LOW


class PartRequirement(BaseModel):
    part_name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1, le=100)
    required: bool = True
    options: list[PartOption] = Field(default_factory=list, max_length=20)


class PartsResearch(BaseModel):
    requirements: list[PartRequirement] = Field(default_factory=list, max_length=50)
    notes: list[str] = Field(default_factory=list, max_length=30)


class ResearchBundle(BaseModel):
    labor: LaborResearch
    parts: PartsResearch
    summary: str = Field(min_length=1, max_length=3000)
    citations: list[Citation] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    request_id: str | None = Field(default=None, max_length=64)
    research_mode: Literal["structured", "json_fallback"] | None = None


class EstimateRequest(BaseModel):
    vehicle: VehicleInput
    job: NonBlank = Field(max_length=500)
    location: LocationInput
    labor_rate: float | None = Field(default=None, ge=0, le=1000)
    mobile_service_fee: float | None = Field(default=None, ge=0, le=10_000)
    shop_supplies_percent: float | None = Field(default=None, ge=0, le=25)
    parts_tax_rate: float | None = Field(default=None, ge=0, le=20)


class SelectedPart(BaseModel):
    part_name: str
    quantity: int
    retailer: str
    brand: str | None = None
    part_number: str | None = None
    unit_price: float
    extended_price: float
    availability: Availability
    store_name: str | None = None
    url: HttpUrl
    confidence: Confidence


class EstimateLaborItem(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    labor_hours: float = Field(ge=0, le=500)
    labor_rate: float = Field(ge=0, le=1_000_000)
    labor_total: float = Field(ge=0, le=1_000_000)


class EstimateFeeItem(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    amount: float = Field(ge=0, le=1_000_000)


class EstimateTotals(BaseModel):
    labor_hours: float
    labor_rate: float
    labor_total: float
    parts_subtotal: float
    shop_supplies: float
    mobile_service_fee: float
    parts_tax: float
    estimated_total: float
    practical_time_low: float
    practical_time_high: float


class EstimateResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    vehicle: DecodedVehicle
    location: ResolvedLocation
    job: str
    research: ResearchBundle
    labor_items: list[EstimateLaborItem] = Field(default_factory=list)
    selected_parts: list[SelectedPart]
    fee_items: list[EstimateFeeItem] = Field(default_factory=list)
    totals: EstimateTotals
    approval_required: bool = False
    approval_reason: str = "Research and estimating run automatically."
    generated_at_utc: str


class ConversationMode(StrEnum):
    DIRECT = "direct"
    AUTO = "auto"
    TEAM = "team"


class MessageOrigin(StrEnum):
    OWNER = "owner"
    AGENT = "agent"
    SYSTEM = "system"


class AgentName(StrEnum):
    DIAGNOSTIC = "diagnostic"
    ESTIMATOR = "estimator"
    PARTS = "parts"
    SERVICE_ADVISOR = "service_advisor"
    OPERATIONS = "operations"
    DOCUMENTATION = "documentation"
    MARKETING = "marketing"
    COMPLIANCE = "compliance"
    QUALITY_CONTROL = "quality_control"


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: NonBlank = Field(max_length=12_000)


class ChatRequest(BaseModel):
    message: NonBlank = Field(max_length=12_000)
    mode: ConversationMode = ConversationMode.AUTO
    location: LocationInput | None = None
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=30)
    requested_agents: list[AgentName] = Field(default_factory=list, max_length=8)


class DelegationRecord(BaseModel):
    agent: AgentName
    reason: str = Field(min_length=1, max_length=500)


class ChatResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    answer: str = Field(min_length=1, max_length=30_000)
    mode: ConversationMode
    speaker: Literal["optimus"] = "optimus"
    consultations: list[DelegationRecord] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    used_web_search: bool = False
    approval_required: bool = False
    approval_reason: str = "Direct owner conversation; no extra approval needed for research."
    generated_at_utc: str


class AuthLoginRequest(BaseModel):
    username: NonBlank = Field(max_length=120)
    password: Password


class ShopSignupRequest(BaseModel):
    business_name: NonBlank = Field(max_length=200)
    owner_display_name: NonBlank = Field(max_length=120)
    username: NonBlank = Field(max_length=120)
    email: NonBlank = Field(max_length=180)
    password: Password


class VerifyEmailRequest(BaseModel):
    token: NonBlank = Field(max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: Password
    new_password: Password


class PasswordResetRequest(BaseModel):
    email: NonBlank = Field(max_length=180)


class PasswordResetConfirmRequest(BaseModel):
    token: NonBlank = Field(max_length=256)
    new_password: Password


class AuthSessionRead(BaseModel):
    id: int
    current: bool
    created_at: datetime
    last_seen_at: datetime | None = None
    expires_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None


class AuthSessionListResponse(BaseModel):
    sessions: list[AuthSessionRead]


class AuthLoginEventRead(BaseModel):
    id: int
    event_type: Literal["succeeded", "failed", "locked", "blocked"]
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime


class AuthLoginHistoryResponse(BaseModel):
    events: list[AuthLoginEventRead]


class AccountSecurityRead(BaseModel):
    account_status: Literal["active", "disabled", "suspended"]
    locked_until: datetime | None = None
    mfa_architecture_ready: bool = True
    active_mfa_factor_count: int = 0


class AuthUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
    email: str | None = None
    email_verified_at: datetime | None = None
    account_status: Literal["active", "disabled", "suspended"] = "active"
    # /goal Phase 8: set only when the current session was minted by
    # support-initiated impersonation (see AuthSession.impersonated_by_user_account_id).
    is_impersonated: bool = False
    impersonated_by_username: str | None = None


class AuthSessionResponse(BaseModel):
    user: AuthUser
    expires_at: datetime
    session_expires_in_seconds: int


class AuthMeResponse(BaseModel):
    authenticated: bool = True
    user: AuthUser
    expires_at: datetime


class ContextScope(StrEnum):
    PROJECT = "project"
    SESSION = "session"


class ContextEntryUpsertRequest(BaseModel):
    value: NonBlank = Field(max_length=4000)
    expected_revision: int | None = Field(default=None, ge=1)


class ContextEntryRead(BaseModel):
    id: int
    project_key: str
    scope: ContextScope
    context_key: str
    value: str
    revision: int
    updated_at: datetime
    stale: bool


class ContextListResponse(BaseModel):
    project_key: str
    scope: ContextScope
    entries: list[ContextEntryRead]
    max_entries: int
    stale_after_hours: int


class ContextDeleteResponse(BaseModel):
    ok: bool = True
    project_key: str
    scope: ContextScope
    context_key: str
    deleted_revision: int


class CustomerBase(BaseModel):
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    company_name: str | None = Field(default=None, max_length=180)
    email: str | None = Field(default=None, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    secondary_phone: str | None = Field(default=None, max_length=40)
    address_line_1: str | None = Field(default=None, max_length=180)
    address_line_2: str | None = Field(default=None, max_length=180)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)
    preferred_contact_method: str | None = Field(default=None, max_length=40)
    internal_notes: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "first_name",
        "last_name",
        "company_name",
        "email",
        "phone",
        "secondary_phone",
        "address_line_1",
        "address_line_2",
        "city",
        "state",
        "postal_code",
        "preferred_contact_method",
        "internal_notes",
        mode="before",
    )
    @classmethod
    def strip_customer_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def require_name_or_company(self) -> CustomerBase:
        has_person_name = bool(self.first_name or self.last_name)
        if not has_person_name and not self.company_name:
            raise ValueError("Provide a first or last name, or a company name.")
        return self


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    company_name: str | None = Field(default=None, max_length=180)
    email: str | None = Field(default=None, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    secondary_phone: str | None = Field(default=None, max_length=40)
    address_line_1: str | None = Field(default=None, max_length=180)
    address_line_2: str | None = Field(default=None, max_length=180)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)
    preferred_contact_method: str | None = Field(default=None, max_length=40)
    internal_notes: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "first_name",
        "last_name",
        "company_name",
        "email",
        "phone",
        "secondary_phone",
        "address_line_1",
        "address_line_2",
        "city",
        "state",
        "postal_code",
        "preferred_contact_method",
        "internal_notes",
        mode="before",
    )
    @classmethod
    def strip_customer_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class CustomerRead(CustomerBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class CustomerListResponse(BaseModel):
    items: list[CustomerRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class CustomerArchiveResponse(BaseModel):
    ok: bool = True
    customer: CustomerRead


class TechnicianBase(BaseModel):
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=180)
    employment_status: str | None = Field(default=None, max_length=40)
    job_title: str | None = Field(default=None, max_length=120)
    hire_date: date | None = None
    hourly_cost: float | None = Field(default=None, ge=0, le=1000)
    certifications: str | None = Field(default=None, max_length=2000)
    certification_expiration: date | None = None
    specialties: str | None = Field(default=None, max_length=2000)
    driver_license_valid: bool | None = None
    insurance_verified: bool | None = None
    normal_availability: str | None = Field(default=None, max_length=500)
    safety_notes: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "first_name",
        "last_name",
        "phone",
        "email",
        "employment_status",
        "job_title",
        "certifications",
        "specialties",
        "normal_availability",
        "safety_notes",
        mode="before",
    )
    @classmethod
    def strip_technician_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def require_name(self) -> TechnicianBase:
        if not (self.first_name or self.last_name):
            raise ValueError("Provide a first or last name.")
        return self


class TechnicianCreate(TechnicianBase):
    pass


class TechnicianUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=180)
    employment_status: str | None = Field(default=None, max_length=40)
    job_title: str | None = Field(default=None, max_length=120)
    hire_date: date | None = None
    hourly_cost: float | None = Field(default=None, ge=0, le=1000)
    certifications: str | None = Field(default=None, max_length=2000)
    certification_expiration: date | None = None
    specialties: str | None = Field(default=None, max_length=2000)
    driver_license_valid: bool | None = None
    insurance_verified: bool | None = None
    normal_availability: str | None = Field(default=None, max_length=500)
    safety_notes: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "first_name",
        "last_name",
        "phone",
        "email",
        "employment_status",
        "job_title",
        "certifications",
        "specialties",
        "normal_availability",
        "safety_notes",
        mode="before",
    )
    @classmethod
    def strip_technician_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class TechnicianRead(TechnicianBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    is_archived: bool
    has_login: bool
    is_clocked_in: bool
    comeback_count: int
    created_at: datetime
    updated_at: datetime


class TechnicianListResponse(BaseModel):
    items: list[TechnicianRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class TechnicianArchiveResponse(BaseModel):
    ok: bool = True
    technician: TechnicianRead


class TechnicianProvisionLoginRequest(BaseModel):
    username: NonBlank = Field(max_length=120)
    password: Password


class TechnicianProvisionLoginResponse(BaseModel):
    ok: bool = True
    technician: TechnicianRead
    username: str


class TechnicianTimeEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    clock_in_at: datetime
    clock_out_at: datetime | None = None
    duration_minutes: int | None = None


class TechnicianClockResponse(BaseModel):
    ok: bool = True
    is_clocked_in: bool
    entry: TechnicianTimeEntryRead


class TechnicianSelfRead(BaseModel):
    """Same shape as `TechnicianRead` minus `hourly_cost` -- that's an
    internal wage/cost field the owner sets and sees, not something a
    technician's own self-service view should expose."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    email: str | None = None
    employment_status: str | None = None
    job_title: str | None = None
    hire_date: date | None = None
    certifications: str | None = None
    certification_expiration: date | None = None
    specialties: str | None = None
    driver_license_valid: bool | None = None
    insurance_verified: bool | None = None
    normal_availability: str | None = None
    safety_notes: str | None = None
    display_name: str
    is_archived: bool
    has_login: bool
    is_clocked_in: bool
    comeback_count: int
    created_at: datetime
    updated_at: datetime


class TechnicianMeResponse(BaseModel):
    technician: TechnicianSelfRead
    recent_time_entries: list[TechnicianTimeEntryRead]
    assigned_work_order_ids: list[int]


class VehicleBase(BaseModel):
    vin: str | None = Field(default=None, max_length=17)
    year: int | None = Field(default=None, ge=1900, le=2100)
    make: NonBlank = Field(max_length=100)
    model: NonBlank = Field(max_length=100)
    trim: str | None = Field(default=None, max_length=120)
    engine: str | None = Field(default=None, max_length=120)
    drivetrain: str | None = Field(default=None, max_length=80)
    transmission: str | None = Field(default=None, max_length=120)
    license_plate: str | None = Field(default=None, max_length=32)
    license_plate_state: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=80)
    current_mileage: int | None = Field(default=None, ge=0, le=1_000_000)
    fleet_unit_number: str | None = Field(default=None, max_length=80)
    internal_notes: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "vin",
        "trim",
        "engine",
        "drivetrain",
        "transmission",
        "license_plate",
        "license_plate_state",
        "color",
        "fleet_unit_number",
        "internal_notes",
        mode="before",
    )
    @classmethod
    def strip_vehicle_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    vin: str | None = Field(default=None, max_length=17)
    year: int | None = Field(default=None, ge=1900, le=2100)
    make: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    trim: str | None = Field(default=None, max_length=120)
    engine: str | None = Field(default=None, max_length=120)
    drivetrain: str | None = Field(default=None, max_length=80)
    transmission: str | None = Field(default=None, max_length=120)
    license_plate: str | None = Field(default=None, max_length=32)
    license_plate_state: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=80)
    current_mileage: int | None = Field(default=None, ge=0, le=1_000_000)
    fleet_unit_number: str | None = Field(default=None, max_length=80)
    internal_notes: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "vin",
        "make",
        "model",
        "trim",
        "engine",
        "drivetrain",
        "transmission",
        "license_plate",
        "license_plate_state",
        "color",
        "fleet_unit_number",
        "internal_notes",
        mode="before",
    )
    @classmethod
    def strip_vehicle_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class VehicleRead(VehicleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    customer_display_name: str | None = None
    display_name: str
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class VehicleListResponse(BaseModel):
    items: list[VehicleRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class VehicleArchiveResponse(BaseModel):
    ok: bool = True
    vehicle: VehicleRead


class EstimateStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DECLINED = "declined"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class EstimatePaymentOptionCode(StrEnum):
    PAY_IN_FULL = "pay_in_full"
    SPLIT_PAYMENT = "split_payment"
    TWO_MONTH_PLAN = "two_month_plan"


class EstimateApprovalMethod(StrEnum):
    LINK = "link"
    INTERNAL = "internal"
    TYPED_SIGNATURE = "typed_signature"


class EstimateCustomerSummary(BaseModel):
    id: int
    display_name: str
    email: str | None = None
    phone: str | None = None


class EstimateVehicleSummary(BaseModel):
    id: int
    customer_id: int
    display_name: str
    vin: str | None = None
    license_plate: str | None = None
    current_mileage: int | None = None


class EstimatePaymentOption(BaseModel):
    code: EstimatePaymentOptionCode
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)
    requires_payment_plan_acknowledgement: bool = False


class EstimateRecordBase(BaseModel):
    customer_id: int = Field(ge=1)
    vehicle_id: int = Field(ge=1)
    job: NonBlank = Field(max_length=500)
    location: LocationInput
    labor_rate: float | None = Field(default=None, ge=0, le=1000)
    mobile_service_fee: float | None = Field(default=None, ge=0, le=10_000)
    shop_supplies_percent: float | None = Field(default=None, ge=0, le=25)
    parts_tax_rate: float | None = Field(default=None, ge=0, le=20)
    terms_text: str = Field(
        default="Customer authorization is required before repair work begins.", max_length=4000
    )
    payment_options: list[EstimatePaymentOption] = Field(default_factory=list, max_length=6)
    expires_in_days: int = Field(default=7, ge=1, le=90)

    @field_validator("terms_text", mode="before")
    @classmethod
    def strip_estimate_terms(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class EstimateCreate(EstimateRecordBase):
    pass


class EstimateUpdate(BaseModel):
    terms_text: str | None = Field(default=None, max_length=4000)
    payment_options: list[EstimatePaymentOption] | None = Field(default=None, max_length=6)
    expires_in_days: int | None = Field(default=None, ge=1, le=90)
    status: EstimateStatus | None = None

    @field_validator("terms_text", mode="before")
    @classmethod
    def strip_estimate_update_terms(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class EstimateRevisionCreate(EstimateRecordBase):
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_revision_reason(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class EstimateSendForApprovalRequest(BaseModel):
    approval_method: EstimateApprovalMethod = EstimateApprovalMethod.LINK
    recipient_name: str | None = Field(default=None, max_length=160)
    expires_in_hours: int = Field(default=72, ge=1, le=720)

    @field_validator("recipient_name", mode="before")
    @classmethod
    def strip_recipient_name(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class EstimateApprovalRevokeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class EstimateApprovalTokenRequest(BaseModel):
    token: NonBlank = Field(max_length=400)


class EstimateApprovalActionRequest(EstimateApprovalTokenRequest):
    revision_number: int = Field(ge=1)
    approving_name: NonBlank = Field(max_length=160)
    accepted_terms: bool
    payment_option: EstimatePaymentOptionCode
    payment_plan_acknowledged: bool = False
    typed_authorization: str | None = Field(default=None, max_length=1000)

    @field_validator("typed_authorization", mode="before")
    @classmethod
    def strip_typed_authorization(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class EstimateDeclineActionRequest(EstimateApprovalTokenRequest):
    revision_number: int = Field(ge=1)
    declining_name: NonBlank = Field(max_length=160)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_decline_reason(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class EstimateApprovalEventRead(BaseModel):
    id: int
    event_type: str
    revision_number: int
    actor_type: str
    actor_name: str | None = None
    approval_method: str | None = None
    accepted_terms: bool | None = None
    payment_option: str | None = None
    payment_plan_acknowledged: bool | None = None
    decline_reason: str | None = None
    content_hash: str
    created_at: datetime


class EstimateRevisionRead(BaseModel):
    id: int
    revision_number: int
    status: EstimateStatus
    customer: EstimateCustomerSummary
    vehicle: EstimateVehicleSummary
    request: EstimateRequest
    estimate: EstimateResponse
    terms_text: str
    payment_options: list[EstimatePaymentOption]
    approval_due_at: datetime | None = None
    content_hash: str
    created_at: datetime


class EstimateRead(BaseModel):
    id: int
    estimate_number: str
    status: EstimateStatus
    customer_id: int
    vehicle_id: int
    customer_display_name: str
    vehicle_display_name: str
    current_revision_number: int
    approved_revision_number: int | None = None
    estimate_total: float | None = None
    payment_option_selected: str | None = None
    expires_at: datetime | None = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    current_revision: EstimateRevisionRead


class EstimateListResponse(BaseModel):
    items: list[EstimateRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class EstimateApprovalSendResponse(BaseModel):
    ok: bool = True
    estimate_id: int
    revision_number: int
    status: EstimateStatus
    expires_at: datetime
    approval_link: str


class EstimateApprovalResearchView(BaseModel):
    """Customer-facing research summary. Internal reasoning (labor basis,
    special tools, risk flags) and competing part options/pricing considered
    during research are intentionally omitted from this public view."""

    summary: str
    warnings: list[str] = Field(default_factory=list)


class EstimateApprovalEstimateView(BaseModel):
    """Narrow, customer-safe projection of ``EstimateResponse`` for the public
    approval link. Excludes unselected part-research options and internal
    labor reasoning that customers should never see."""

    job: str
    labor_items: list[EstimateLaborItem] = Field(default_factory=list)
    selected_parts: list[SelectedPart]
    fee_items: list[EstimateFeeItem] = Field(default_factory=list)
    totals: EstimateTotals
    research: EstimateApprovalResearchView


class EstimateApprovalRevisionView(BaseModel):
    """Narrow, customer-safe projection of ``EstimateRevisionRead``. Excludes
    the internal generation request, which may carry raw labor rate, mobile
    service fee, shop supplies percent, and parts tax rate overrides."""

    id: int
    revision_number: int
    status: EstimateStatus
    customer: EstimateCustomerSummary
    vehicle: EstimateVehicleSummary
    estimate: EstimateApprovalEstimateView
    terms_text: str
    payment_options: list[EstimatePaymentOption]
    approval_due_at: datetime | None = None
    content_hash: str
    created_at: datetime


class EstimateApprovalPublicView(BaseModel):
    """Customer-facing approval-link view returned by
    ``POST /api/estimate-approval/view``. Excludes internal research detail
    and raw request overrides that the authenticated owner endpoints
    (``EstimateRead``/``EstimateRevisionRead``) still expose in full."""

    estimate_id: int
    estimate_number: str
    status: EstimateStatus
    revision: EstimateApprovalRevisionView
    token_expires_at: datetime
    token_status: str
    can_approve: bool
    can_decline: bool


class EstimateApprovalActionResponse(BaseModel):
    ok: bool = True
    estimate_id: int
    estimate_number: str
    status: EstimateStatus
    revision_number: int
    decided_at: datetime


class EstimateApprovalAuditResponse(BaseModel):
    estimate_id: int
    estimate_number: str
    status: EstimateStatus
    active_approval_request_id: int | None = None
    events: list[EstimateApprovalEventRead]


class WorkOrderStatus(StrEnum):
    PENDING_REQUIREMENTS = "pending_requirements"
    READY_TO_SCHEDULE = "ready_to_schedule"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_PARTS = "waiting_for_parts"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkOrderNoteVisibility(StrEnum):
    INTERNAL = "internal"
    CUSTOMER = "customer"


class WorkOrderUpdate(BaseModel):
    diagnosis: str | None = Field(default=None, max_length=10_000)
    scheduled_for: datetime | None = None
    deposit_received: bool | None = None
    authorization_confirmed: bool | None = None
    is_comeback: bool | None = None

    @field_validator("diagnosis", mode="before")
    @classmethod
    def strip_work_order_diagnosis(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class WorkOrderAssignTechnicianRequest(BaseModel):
    technician_id: int | None = None


class WorkOrderStatusUpdate(BaseModel):
    status: WorkOrderStatus
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_work_order_status_reason(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class WorkOrderNoteCreate(BaseModel):
    note: NonBlank = Field(max_length=4000)
    visibility: WorkOrderNoteVisibility = WorkOrderNoteVisibility.INTERNAL


class WorkOrderStatusEventRead(BaseModel):
    id: int
    from_status: WorkOrderStatus | None = None
    to_status: WorkOrderStatus
    reason: str | None = None
    created_by_user_id: int | None = None
    created_by_display_name: str | None = None
    created_at: datetime


class WorkOrderNoteRead(BaseModel):
    id: int
    visibility: WorkOrderNoteVisibility
    note: str
    created_by_user_id: int | None = None
    created_by_display_name: str | None = None
    created_at: datetime


class WorkOrderRead(BaseModel):
    id: int
    estimate_id: int
    estimate_revision_id: int
    estimate_number: str
    customer_id: int
    vehicle_id: int
    customer_display_name: str
    vehicle_display_name: str
    title: str
    complaint: str
    diagnosis: str | None = None
    status: WorkOrderStatus
    estimate_total: float | None = None
    labor_hours_estimate: float | None = None
    payment_option_selected: str | None = None
    invoice_id: int | None = None
    invoice_number: str | None = None
    invoice_status: InvoiceStatus | None = None
    deposit_received: bool
    authorization_confirmed: bool
    scheduled_for: datetime | None = None
    assigned_technician_id: int | None = None
    assigned_technician_display_name: str | None = None
    is_comeback: bool
    allowed_next_statuses: list[WorkOrderStatus] = Field(default_factory=list)
    blocked_transitions: dict[str, str] = Field(default_factory=dict)
    source_revision: EstimateRevisionRead
    status_history: list[WorkOrderStatusEventRead] = Field(default_factory=list)
    notes: list[WorkOrderNoteRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WorkOrderListResponse(BaseModel):
    items: list[WorkOrderRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class InvoiceLineItemKind(StrEnum):
    LABOR = "labor"
    PART = "part"
    FEE = "fee"


class PaymentAppliesTo(StrEnum):
    DEPOSIT = "deposit"
    INSTALLMENT = "installment"
    BALANCE = "balance"
    FULL = "full"
    OTHER = "other"


class InvoiceCustomerSnapshot(BaseModel):
    display_name: str
    email: str | None = None
    phone: str | None = None


class InvoiceVehicleSnapshot(BaseModel):
    display_name: str
    vin: str | None = None
    license_plate: str | None = None
    current_mileage: int | None = None


class InvoiceLineItemRead(BaseModel):
    id: int
    sort_order: int
    kind: InvoiceLineItemKind
    description: str
    quantity: float
    unit_amount: float
    line_total: float


class InvoicePaymentCreate(BaseModel):
    amount: float = Field(gt=0, le=1_000_000)
    method_label: NonBlank = Field(max_length=60)
    applies_to: PaymentAppliesTo = PaymentAppliesTo.OTHER
    note: str | None = Field(default=None, max_length=2000)
    recorded_at: datetime | None = None

    @field_validator("note", mode="before")
    @classmethod
    def strip_payment_note(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class InvoicePaymentVoidRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_void_reason(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class InvoicePaymentRead(BaseModel):
    id: int
    amount: float
    method_label: str
    applies_to: PaymentAppliesTo
    note: str | None = None
    recorded_at: datetime
    reversal_of_payment_id: int | None = None
    is_reversal: bool
    created_by_user_id: int | None = None
    created_by_display_name: str | None = None
    created_at: datetime


class PaymentScheduleEntryRead(BaseModel):
    id: int
    sort_order: int
    label: str
    due_at: datetime | None = None
    amount: float


class InvoiceRead(BaseModel):
    id: int
    invoice_number: str
    status: InvoiceStatus
    work_order_id: int
    estimate_id: int
    estimate_revision_id: int
    customer_id: int
    vehicle_id: int
    customer: InvoiceCustomerSnapshot
    vehicle: InvoiceVehicleSnapshot
    title: str
    complaint: str
    payment_option_selected: str | None = None
    issued_at: datetime | None = None
    due_at: datetime | None = None
    labor_total: float
    parts_total: float
    fees_total: float
    invoice_total: float
    total_paid: float
    balance_due: float
    is_overdue: bool
    square_invoice_id: str | None = None
    square_status: str | None = None
    square_payment_url: str | None = None
    line_items: list[InvoiceLineItemRead] = Field(default_factory=list)
    payments: list[InvoicePaymentRead] = Field(default_factory=list)
    schedule: list[PaymentScheduleEntryRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class InvoiceListResponse(BaseModel):
    items: list[InvoiceRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class InvoiceIssueRequest(BaseModel):
    due_in_days: int = Field(default=30, ge=1, le=180)


class ApprovalBase(BaseModel):
    work_order_id: int
    status: str = Field(default="pending", max_length=30)
    requested_reason: str | None = Field(default=None, max_length=4000)
    decision_reason: str | None = Field(default=None, max_length=4000)


class ApprovalCreate(ApprovalBase):
    pass


class ApprovalUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=30)
    requested_reason: str | None = Field(default=None, max_length=4000)
    decision_reason: str | None = Field(default=None, max_length=4000)


class ApprovalRead(ApprovalBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None = None
    decided_by_user_id: int | None = None
    customer_name: str | None = None
    vehicle_name: str | None = None
    work_order_title: str | None = None


class ApprovalDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=4000)


class CustomerHistoryEstimateItem(BaseModel):
    id: int
    estimate_number: str
    status: EstimateStatus
    vehicle_display_name: str
    estimate_total: float | None = None
    created_at: datetime
    updated_at: datetime


class CustomerHistoryWorkOrderItem(BaseModel):
    id: int
    estimate_number: str
    title: str
    status: WorkOrderStatus
    invoice_id: int | None = None
    updated_at: datetime


class CustomerHistoryInvoiceItem(BaseModel):
    id: int
    invoice_number: str
    status: InvoiceStatus
    invoice_total: float
    balance_due: float
    is_overdue: bool
    issued_at: datetime | None = None
    due_at: datetime | None = None


class CustomerHistoryEstimateSection(BaseModel):
    items: list[CustomerHistoryEstimateItem]
    total: int


class CustomerHistoryWorkOrderSection(BaseModel):
    items: list[CustomerHistoryWorkOrderItem]
    total: int


class CustomerHistoryInvoiceSection(BaseModel):
    items: list[CustomerHistoryInvoiceItem]
    total: int


class CustomerHistoryResponse(BaseModel):
    customer_id: int
    customer_display_name: str
    estimates: CustomerHistoryEstimateSection
    work_orders: CustomerHistoryWorkOrderSection
    invoices: CustomerHistoryInvoiceSection


class NotificationEntityType(StrEnum):
    ESTIMATE = "estimate"
    WORK_ORDER = "work_order"
    INVOICE = "invoice"


class NotificationEvent(StrEnum):
    ESTIMATE_SENT = "estimate_sent"
    ESTIMATE_APPROVED = "estimate_approved"
    ESTIMATE_DECLINED = "estimate_declined"
    WORK_ORDER_STATUS_CHANGED = "work_order_status_changed"
    INVOICE_ISSUED = "invoice_issued"
    PAYMENT_RECORDED = "payment_recorded"
    PAYMENT_VOIDED = "payment_voided"


class NotificationRead(BaseModel):
    id: int
    entity_type: NotificationEntityType
    entity_id: int
    event: NotificationEvent
    title: str
    body: str | None = None
    read_at: datetime | None = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationRead]
    page: int
    page_size: int
    total: int
    unread_count: int
    has_more: bool


class NotificationMarkReadResponse(BaseModel):
    ok: bool
    unread_count: int


class DashboardMetric(BaseModel):
    """A single Overview metric. `available=False` means the shop's data
    model doesn't support this metric yet (e.g. no COGS/expense tracking
    exists anywhere in the schema) -- the frontend must render the honest
    `unavailable_reason` message, never a fabricated number."""

    key: str
    label: str
    available: bool
    value: float | None = None
    previous_value: float | None = None
    change_percent: float | None = None
    unavailable_reason: str | None = None


class DashboardTrendPoint(BaseModel):
    period_label: str
    period_start: datetime
    values: dict[str, float]


class DashboardWorkOrderStatusCount(BaseModel):
    status: WorkOrderStatus
    count: int


class DashboardRevenueBreakdownItem(BaseModel):
    label: str
    amount: float
    percent: float


class DashboardInsightPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DashboardInsight(BaseModel):
    key: str
    priority: DashboardInsightPriority
    issue: str
    metric: str
    recommended_action: str
    link_view: str
    link_record_id: int | None = None
    generated_at: datetime


class DashboardUpcomingInstallment(BaseModel):
    invoice_id: int
    invoice_number: str
    label: str
    amount: float
    due_at: datetime | None = None


class DashboardCurrentOperations(BaseModel):
    open_work_orders: int
    in_progress: int
    waiting_on_parts: int
    awaiting_customer_approval: int
    completed_not_invoiced: int
    ready_for_pickup_note: str


class DashboardFinancialObligations(BaseModel):
    outstanding_balance: float
    overdue_balance: float
    overdue_invoice_count: int
    upcoming_installments: list[DashboardUpcomingInstallment]
    deposits_received_total: float


class DashboardSummaryResponse(BaseModel):
    date_from: datetime
    date_to: datetime
    metrics: list[DashboardMetric]
    revenue_trend: list[DashboardTrendPoint]
    work_order_trend: list[DashboardTrendPoint]
    revenue_breakdown: list[DashboardRevenueBreakdownItem]
    gross_profit_margin: DashboardMetric
    approval_conversion_rate: DashboardMetric
    accounts_receivable_health: DashboardMetric
    work_orders_by_status: list[DashboardWorkOrderStatusCount]
    current_operations: DashboardCurrentOperations
    financial_obligations: DashboardFinancialObligations
    insights: list[DashboardInsight]


class PaymentActivityEntryRead(BaseModel):
    id: int
    invoice_id: int
    invoice_number: str
    amount: float
    applies_to: PaymentAppliesTo
    method_label: str
    recorded_at: datetime
    is_reversal: bool


class PaymentActivityBreakdownItem(BaseModel):
    label: str
    total: float
    count: int


class PaymentActivityReportResponse(BaseModel):
    date_from: datetime
    date_to: datetime
    entries: list[PaymentActivityEntryRead]
    total_collected: float
    payment_count: int
    by_method: list[PaymentActivityBreakdownItem]
    by_applies_to: list[PaymentActivityBreakdownItem]


class TechnicianTimeSummaryRead(BaseModel):
    technician_id: int
    technician_display_name: str
    clocked_hours: float
    labor_cost: float | None = None
    open_entry_count: int


class TechnicianTimeReportResponse(BaseModel):
    date_from: datetime
    date_to: datetime
    technicians: list[TechnicianTimeSummaryRead]
    total_clocked_hours: float
    total_labor_cost: float
    technicians_missing_hourly_cost: int
    billed_hours: DashboardMetric
    commission: DashboardMetric


class LowStockPartRead(BaseModel):
    part_id: int
    part_number: str
    description: str
    quantity_on_hand: int
    reorder_threshold: int
    vendor_display_name: str | None = None


class InventoryValuationReportResponse(BaseModel):
    """A point-in-time snapshot (not date-ranged, unlike the other reports --
    inventory valuation reflects current stock, not activity over a period).
    `total_valuation` only sums parts with a recorded `unit_cost`; parts
    missing one are excluded from the dollar total (not assigned a
    fabricated cost) and counted in `parts_missing_cost_count` instead."""

    total_valuation: float
    total_units_on_hand: int
    parts_counted: int
    parts_missing_cost_count: int
    low_stock_parts: list[LowStockPartRead]


class PartUsageEntryRead(BaseModel):
    """`cost_total` only sums usage events with a recorded
    `unit_cost_snapshot`; usage missing one is excluded from the dollar total
    (not assigned a fabricated cost) and counted in `quantity_missing_cost`
    instead -- same disclosure pattern as Gross Profit and Inventory
    Valuation above."""

    part_id: int
    part_number: str
    description: str
    quantity_used: int
    cost_total: float
    quantity_missing_cost: int


class PartsUsageReportResponse(BaseModel):
    date_from: datetime
    date_to: datetime
    parts: list[PartUsageEntryRead]
    total_quantity_used: int
    total_cost: float
    total_quantity_missing_cost: int


class VendorPurchasingBreakdownItem(BaseModel):
    vendor_id: int
    vendor_name: str
    order_count: int
    total_spend: float


class VendorPurchasingReportResponse(BaseModel):
    """Only purchase orders that were actually submitted (`submitted_at` in
    the window) count toward spend -- drafts never became a real commitment.
    Submitted-then-cancelled orders are excluded from spend and counted
    separately in `cancelled_order_count` rather than counted as real spend
    that never happened."""

    date_from: datetime
    date_to: datetime
    by_vendor: list[VendorPurchasingBreakdownItem]
    total_spend: float
    total_orders: int
    cancelled_order_count: int


class WorkOrderCycleTimeReportResponse(BaseModel):
    """Cycle time is measured from work-order creation to its first (and,
    since `completed` is a terminal status, only) transition into
    `completed` -- total elapsed calendar time, not active wrench time, so a
    job that spent days waiting on a backordered part still counts that wait
    toward its cycle time. `comeback_rate_percent` reflects the owner's own
    manual `WorkOrder.is_comeback` flag (set via the existing work-order
    detail checkbox) among completed work orders in the window -- OptimusOS
    does not attempt to automatically detect comebacks (e.g. same
    vehicle/same complaint within N days); that would require a business
    rule the owner hasn't defined yet."""

    date_from: datetime
    date_to: datetime
    completed_work_order_count: int
    average_cycle_time_hours: float
    median_cycle_time_hours: float
    fastest_cycle_time_hours: float
    slowest_cycle_time_hours: float
    comeback_count: int
    comeback_rate_percent: float


class DiagnosticInspectionReportResponse(BaseModel):
    """Diagnostic findings and inspections are two separate, differently-shaped
    logs, reported together since both are real technician-observation
    records from the same window. Diagnostic findings have no structured
    status field, so `findings_missing_conclusion` -- findings with no
    `conclusion` recorded yet, i.e. diagnosis still open -- is the honest
    disclosure available rather than a fabricated category. Inspection items
    DO have a structured status (`ok`/`attention`/`fail`, enforced by
    `InspectionItem` at the application layer even though storage is a JSON
    column), so `items_ok`/`items_attention`/`items_fail` are a genuine
    breakdown, not an approximation. Counts activity created in the window
    regardless of a finding/inspection's current archived status -- archiving
    is a later administrative action, not a retroactive undo of activity
    that already happened."""

    date_from: datetime
    date_to: datetime
    diagnostic_finding_count: int
    findings_missing_conclusion: int
    inspection_count: int
    inspection_item_count: int
    items_ok: int
    items_attention: int
    items_fail: int


class VendorBase(BaseModel):
    name: NonBlank = Field(max_length=180)
    contact_name: str | None = Field(default=None, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=180)
    address_line_1: str | None = Field(default=None, max_length=180)
    address_line_2: str | None = Field(default=None, max_length=180)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "contact_name",
        "phone",
        "email",
        "address_line_1",
        "address_line_2",
        "city",
        "state",
        "postal_code",
        "notes",
        mode="before",
    )
    @classmethod
    def strip_vendor_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class VendorCreate(VendorBase):
    pass


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    contact_name: str | None = Field(default=None, max_length=180)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=180)
    address_line_1: str | None = Field(default=None, max_length=180)
    address_line_2: str | None = Field(default=None, max_length=180)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "name",
        "contact_name",
        "phone",
        "email",
        "address_line_1",
        "address_line_2",
        "city",
        "state",
        "postal_code",
        "notes",
        mode="before",
    )
    @classmethod
    def strip_vendor_update_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class VendorRead(VendorBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_archived: bool
    part_count: int
    created_at: datetime
    updated_at: datetime


class VendorListResponse(BaseModel):
    items: list[VendorRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class VendorArchiveResponse(BaseModel):
    ok: bool = True
    vendor: VendorRead


class PartBase(BaseModel):
    part_number: NonBlank = Field(max_length=120)
    description: NonBlank = Field(max_length=300)
    category: str | None = Field(default=None, max_length=120)
    quantity_on_hand: int = Field(default=0, ge=0)
    reorder_threshold: int | None = Field(default=None, ge=0)
    unit_cost: float | None = Field(default=None, ge=0)
    unit_price: float | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=4000)
    vendor_id: int | None = None

    @field_validator("part_number", "description", "category", "location", "notes", mode="before")
    @classmethod
    def strip_part_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class PartCreate(PartBase):
    pass


class PartUpdate(BaseModel):
    part_number: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=120)
    quantity_on_hand: int | None = Field(default=None, ge=0)
    reorder_threshold: int | None = Field(default=None, ge=0)
    unit_cost: float | None = Field(default=None, ge=0)
    unit_price: float | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=4000)
    vendor_id: int | None = None

    @field_validator("part_number", "description", "category", "location", "notes", mode="before")
    @classmethod
    def strip_part_update_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class PartRead(PartBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vendor_name: str | None = None
    is_archived: bool
    is_below_reorder_threshold: bool
    created_at: datetime
    updated_at: datetime


class PartListResponse(BaseModel):
    items: list[PartRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class PartArchiveResponse(BaseModel):
    ok: bool = True
    part: PartRead


class PurchaseOrderStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class PurchaseOrderLineItemCreate(BaseModel):
    part_id: int
    quantity_ordered: int = Field(gt=0, le=100_000)
    unit_cost: float = Field(ge=0)


class PurchaseOrderLineItemRead(BaseModel):
    id: int
    part_id: int
    part_number: str
    part_description: str
    quantity_ordered: int
    quantity_received: int
    unit_cost: float
    line_total: float


class PurchaseOrderCreate(BaseModel):
    vendor_id: int
    notes: str | None = Field(default=None, max_length=4000)
    line_items: list[PurchaseOrderLineItemCreate] = Field(min_length=1, max_length=200)

    @field_validator("notes", mode="before")
    @classmethod
    def strip_purchase_order_notes(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class PurchaseOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    po_number: str
    vendor_id: int
    vendor_name: str
    status: PurchaseOrderStatus
    notes: str | None = None
    line_items: list[PurchaseOrderLineItemRead]
    subtotal: float
    total: float
    submitted_at: datetime | None = None
    received_at: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PurchaseOrderListResponse(BaseModel):
    items: list[PurchaseOrderRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class PurchaseOrderReceiveRequest(BaseModel):
    line_item_id: int
    quantity: int = Field(gt=0, le=100_000)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note", mode="before")
    @classmethod
    def strip_purchase_order_receive_note(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class PurchaseOrderReceiptRead(BaseModel):
    id: int
    line_item_id: int
    quantity_received: int
    received_by_display_name: str | None = None
    note: str | None = None
    created_at: datetime


class PurchaseOrderReceiptsResponse(BaseModel):
    purchase_order_id: int
    receipts: list[PurchaseOrderReceiptRead]


class PartAllocationCreate(BaseModel):
    part_id: int
    quantity_required: int = Field(gt=0, le=100_000)


class PartAllocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_order_id: int
    part_id: int
    part_number: str
    part_description: str
    quantity_required: int
    quantity_allocated: int
    quantity_used: int
    quantity_returned: int
    unit_cost_snapshot: float | None = None
    created_at: datetime
    updated_at: datetime


class PartAllocationTechnicianRead(BaseModel):
    """Same shape as `PartAllocationRead` minus `unit_cost_snapshot` -- that's
    an internal cost-basis field (it feeds the owner's Gross Profit
    calculation, see `docs/context/KNOWN_ISSUES.md`) that a technician's own
    view of a part allocation should not expose, same reasoning as
    `TechnicianSelfRead` omitting `hourly_cost`."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    work_order_id: int
    part_id: int
    part_number: str
    part_description: str
    quantity_required: int
    quantity_allocated: int
    quantity_used: int
    quantity_returned: int
    created_at: datetime
    updated_at: datetime


class PartAllocationListResponse(BaseModel):
    items: list[PartAllocationRead | PartAllocationTechnicianRead]


class PartAllocationAllocateRequest(BaseModel):
    quantity: int = Field(gt=0, le=100_000)
    override: bool = False
    override_reason: str | None = Field(default=None, max_length=500)

    @field_validator("override_reason", mode="before")
    @classmethod
    def strip_override_reason(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class PartAllocationUseRequest(BaseModel):
    quantity: int = Field(gt=0, le=100_000)


class PartAllocationReturnRequest(BaseModel):
    quantity: int = Field(gt=0, le=100_000)


class PartAllocationEventRead(BaseModel):
    id: int
    event_type: str
    quantity_delta: int
    actor_type: str
    actor_name: str | None = None
    inventory_override: bool
    override_reason: str | None = None
    created_at: datetime


class PartAllocationEventsResponse(BaseModel):
    allocation_id: int
    events: list[PartAllocationEventRead]


class IntakeSourceCode(StrEnum):
    PHONE = "phone"
    WALK_IN = "walk_in"
    WEB = "web"
    REFERRAL = "referral"


class IntakeStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    SCHEDULED = "scheduled"
    CONVERTED = "converted"
    DISMISSED = "dismissed"


class IntakeRequestBase(BaseModel):
    customer_name: NonBlank = Field(max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=180)
    vehicle_description: str | None = Field(default=None, max_length=300)
    complaint: NonBlank = Field(max_length=4000)
    source: IntakeSourceCode = IntakeSourceCode.PHONE
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("phone", "email", "vehicle_description", "notes", mode="before")
    @classmethod
    def strip_intake_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class IntakeRequestCreate(IntakeRequestBase):
    pass


class IntakeRequestUpdate(BaseModel):
    customer_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=180)
    vehicle_description: str | None = Field(default=None, max_length=300)
    complaint: str | None = Field(default=None, min_length=1, max_length=4000)
    source: IntakeSourceCode | None = None
    status: IntakeStatus | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("phone", "email", "vehicle_description", "notes", mode="before")
    @classmethod
    def strip_intake_update_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class IntakeRequestRead(IntakeRequestBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: IntakeStatus
    converted_customer_id: int | None = None
    converted_vehicle_id: int | None = None
    created_at: datetime
    updated_at: datetime


class IntakeRequestListResponse(BaseModel):
    items: list[IntakeRequestRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class IntakeRequestConvertRequest(BaseModel):
    """Vehicle fields are optional -- an intake request can convert to just
    a customer record when no vehicle detail was captured yet."""

    vehicle_year: int | None = Field(default=None, ge=1900, le=2100)
    vehicle_make: str | None = Field(default=None, max_length=100)
    vehicle_model: str | None = Field(default=None, max_length=100)
    vehicle_vin: str | None = Field(default=None, max_length=17)


class IntakeRequestConvertResponse(BaseModel):
    ok: bool = True
    intake_request: IntakeRequestRead
    customer: CustomerRead
    vehicle: VehicleRead | None = None


class DiagnosticFindingBase(BaseModel):
    vehicle_id: int
    work_order_id: int | None = None
    technician_id: int | None = None
    codes: str | None = Field(default=None, max_length=2000)
    symptoms: NonBlank = Field(max_length=4000)
    tests_performed: str | None = Field(default=None, max_length=4000)
    conclusion: str | None = Field(default=None, max_length=4000)

    @field_validator("codes", "tests_performed", "conclusion", mode="before")
    @classmethod
    def strip_diagnostic_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class DiagnosticFindingCreate(DiagnosticFindingBase):
    pass


class DiagnosticFindingUpdate(BaseModel):
    work_order_id: int | None = None
    technician_id: int | None = None
    codes: str | None = Field(default=None, max_length=2000)
    symptoms: str | None = Field(default=None, min_length=1, max_length=4000)
    tests_performed: str | None = Field(default=None, max_length=4000)
    conclusion: str | None = Field(default=None, max_length=4000)

    @field_validator("codes", "tests_performed", "conclusion", mode="before")
    @classmethod
    def strip_diagnostic_update_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class DiagnosticFindingRead(DiagnosticFindingBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_display_name: str | None = None
    technician_display_name: str | None = None
    is_archived: bool
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DiagnosticFindingListResponse(BaseModel):
    items: list[DiagnosticFindingRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class DiagnosticFindingArchiveResponse(BaseModel):
    ok: bool = True
    finding: DiagnosticFindingRead


class DiagnosticFindingEventRead(BaseModel):
    id: int
    event_type: str
    actor_type: str
    actor_name: str | None = None
    created_at: datetime


class DiagnosticFindingEventsResponse(BaseModel):
    finding_id: int
    events: list[DiagnosticFindingEventRead]


class InspectionItem(BaseModel):
    label: NonBlank = Field(max_length=200)
    status: Literal["ok", "attention", "fail"] = "ok"
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note", mode="before")
    @classmethod
    def strip_inspection_item_note(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class InspectionBase(BaseModel):
    vehicle_id: int
    work_order_id: int | None = None
    technician_id: int | None = None
    inspection_type: str | None = Field(default=None, max_length=120)
    items: list[InspectionItem] = Field(default_factory=list, max_length=200)
    overall_notes: str | None = Field(default=None, max_length=4000)

    @field_validator("inspection_type", "overall_notes", mode="before")
    @classmethod
    def strip_inspection_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class InspectionCreate(InspectionBase):
    pass


class InspectionUpdate(BaseModel):
    work_order_id: int | None = None
    technician_id: int | None = None
    inspection_type: str | None = Field(default=None, max_length=120)
    items: list[InspectionItem] | None = Field(default=None, max_length=200)
    overall_notes: str | None = Field(default=None, max_length=4000)

    @field_validator("inspection_type", "overall_notes", mode="before")
    @classmethod
    def strip_inspection_update_strings(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class InspectionRead(InspectionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_display_name: str | None = None
    technician_display_name: str | None = None
    has_attention_items: bool
    has_failed_items: bool
    is_archived: bool
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class InspectionListResponse(BaseModel):
    items: list[InspectionRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class InspectionArchiveResponse(BaseModel):
    ok: bool = True
    inspection: InspectionRead


class InspectionEventRead(BaseModel):
    id: int
    event_type: str
    actor_type: str
    actor_name: str | None = None
    created_at: datetime


class InspectionEventsResponse(BaseModel):
    inspection_id: int
    events: list[InspectionEventRead]


class AppointmentStatus(StrEnum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELED = "canceled"
    NO_SHOW = "no_show"


class ServiceLocation(StrEnum):
    SHOP = "shop"
    MOBILE = "mobile"


class BayBase(BaseModel):
    name: NonBlank = Field(max_length=120)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes", mode="before")
    @classmethod
    def strip_bay_notes(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class BayCreate(BayBase):
    pass


class BayUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes", mode="before")
    @classmethod
    def strip_bay_update_notes(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class BayRead(BayBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class BayListResponse(BaseModel):
    items: list[BayRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class BayArchiveResponse(BaseModel):
    bay: BayRead


class WorkingHoursBase(BaseModel):
    technician_id: int
    day_of_week: int = Field(ge=0, le=6)
    start_minute: int = Field(ge=0, lt=1440)
    end_minute: int = Field(gt=0, le=1440)

    @model_validator(mode="after")
    def require_end_after_start(self) -> WorkingHoursBase:
        if self.end_minute <= self.start_minute:
            raise ValueError("end_minute must be later than start_minute.")
        return self


class WorkingHoursCreate(WorkingHoursBase):
    pass


class WorkingHoursUpdate(BaseModel):
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    start_minute: int | None = Field(default=None, ge=0, lt=1440)
    end_minute: int | None = Field(default=None, gt=0, le=1440)


class WorkingHoursRead(WorkingHoursBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class WorkingHoursListResponse(BaseModel):
    items: list[WorkingHoursRead]


class ScheduleBlockBase(BaseModel):
    technician_id: int | None = None
    bay_id: int | None = None
    start_time: datetime
    end_time: datetime
    reason: NonBlank = Field(max_length=200)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes", mode="before")
    @classmethod
    def strip_schedule_block_notes(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def require_end_after_start(self) -> ScheduleBlockBase:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time.")
        return self

    @model_validator(mode="after")
    def require_single_scope(self) -> ScheduleBlockBase:
        if self.technician_id is not None and self.bay_id is not None:
            raise ValueError(
                "A schedule block can target a technician or a bay, not both -- create two"
                " separate blocks if both need to be unavailable."
            )
        return self


class ScheduleBlockCreate(ScheduleBlockBase):
    pass


class ScheduleBlockUpdate(BaseModel):
    technician_id: int | None = None
    bay_id: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes", mode="before")
    @classmethod
    def strip_schedule_block_update_notes(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class ScheduleBlockRead(ScheduleBlockBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    technician_display_name: str | None = None
    bay_name: str | None = None
    created_at: datetime
    updated_at: datetime


class ScheduleBlockListResponse(BaseModel):
    items: list[ScheduleBlockRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class AppointmentBase(BaseModel):
    customer_id: int
    vehicle_id: int
    work_order_id: int | None = None
    technician_id: int
    bay_id: int | None = None
    service_type: NonBlank = Field(max_length=160)
    service_location: ServiceLocation = ServiceLocation.SHOP
    start_time: datetime
    end_time: datetime
    travel_buffer_minutes: int = Field(default=0, ge=0, le=480)
    customer_notes: str | None = Field(default=None, max_length=4000)
    internal_notes: str | None = Field(default=None, max_length=4000)

    @field_validator("customer_notes", "internal_notes", mode="before")
    @classmethod
    def strip_appointment_notes(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def require_end_after_start(self) -> AppointmentBase:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time.")
        return self


class AppointmentCreate(AppointmentBase):
    status: Literal[AppointmentStatus.TENTATIVE, AppointmentStatus.CONFIRMED] = (
        AppointmentStatus.TENTATIVE
    )


class AppointmentUpdate(BaseModel):
    customer_id: int | None = None
    vehicle_id: int | None = None
    work_order_id: int | None = None
    technician_id: int | None = None
    bay_id: int | None = None
    service_type: str | None = Field(default=None, min_length=1, max_length=160)
    service_location: ServiceLocation | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    travel_buffer_minutes: int | None = Field(default=None, ge=0, le=480)
    status: (
        Literal[
            AppointmentStatus.TENTATIVE,
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.IN_PROGRESS,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.NO_SHOW,
        ]
        | None
    ) = None
    customer_notes: str | None = Field(default=None, max_length=4000)
    internal_notes: str | None = Field(default=None, max_length=4000)

    @field_validator("customer_notes", "internal_notes", mode="before")
    @classmethod
    def strip_appointment_update_notes(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class AppointmentMoveRequest(BaseModel):
    start_time: datetime
    end_time: datetime
    technician_id: int | None = None
    bay_id: int | None = None
    travel_buffer_minutes: int | None = Field(default=None, ge=0, le=480)

    @model_validator(mode="after")
    def require_end_after_start(self) -> AppointmentMoveRequest:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time.")
        return self


class AppointmentCancelRequest(BaseModel):
    cancellation_reason: NonBlank = Field(max_length=500)


class AppointmentRead(AppointmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: AppointmentStatus
    customer_display_name: str | None = None
    vehicle_display_name: str | None = None
    technician_display_name: str | None = None
    bay_name: str | None = None
    created_at: datetime
    updated_at: datetime
    canceled_at: datetime | None = None
    cancellation_reason: str | None = None


class AppointmentListResponse(BaseModel):
    items: list[AppointmentRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class AppointmentConflictDetail(BaseModel):
    code: str
    message: str
    conflicting_appointment_id: int | None = None
    conflicting_schedule_block_id: int | None = None


class AvailabilityWindow(BaseModel):
    start_time: datetime
    end_time: datetime


class AvailabilityResponse(BaseModel):
    technician_id: int
    bay_id: int | None = None
    date_from: datetime
    date_to: datetime
    working_windows: list[AvailabilityWindow]
    busy_windows: list[AvailabilityWindow]
    blocked_windows: list[AvailabilityWindow]


class SyntheticTechnicianRequest(BaseModel):
    owner_username: NonBlank = Field(max_length=120)


class SyntheticAccountResponse(BaseModel):
    user_id: int
    username: str
    password: str
    role: Literal["owner", "manager", "technician"]
    technician_id: int | None = None


class SyntheticCleanupResponse(BaseModel):
    deleted_count: int


class ConcurrencyProbeResponse(BaseModel):
    max_observed_in_flight: int


class ShopRole(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    TECHNICIAN = "technician"


class ShopStatus(StrEnum):
    PILOT = "pilot"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class ShopRead(BaseModel):
    id: int
    legal_business_name: str | None = None
    display_name: str
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    phone: str | None = None
    email: str | None = None
    timezone: str
    currency: str
    status: ShopStatus
    created_at: datetime
    updated_at: datetime


class ShopSettingsRead(BaseModel):
    shop_id: int
    labor_rate: float | None = None
    mobile_service_fee: float | None = None
    shop_supplies_percent: float | None = None
    parts_tax_rate: float | None = None
    operating_hours: dict | None = None
    service_area: dict | None = None
    estimate_terms_text: str | None = None
    invoice_terms_text: str | None = None
    payment_plan_settings: dict | None = None
    branding_reference: str | None = None


class ShopMembershipRead(BaseModel):
    id: int
    shop_id: int
    user_account_id: int
    role: ShopRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ShopInvitationRead(BaseModel):
    id: int
    shop_id: int
    email: str
    role: ShopRole
    invited_by_user_account_id: int
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime


class ShopInvitationCreate(BaseModel):
    email: NonBlank = Field(max_length=180)
    role: ShopRole


class ShopInvitationAccept(BaseModel):
    token: NonBlank = Field(max_length=256)
    display_name: NonBlank = Field(max_length=120)
    username: NonBlank = Field(max_length=120)
    password: Password


class ShopInvitationAcceptResponse(BaseModel):
    accepted: bool = True
    user: AuthUser


class AccountStatusUpdate(BaseModel):
    status: Literal["active", "disabled", "suspended"]


class ShopMemberRead(BaseModel):
    user_account_id: int
    display_name: str
    username: str
    email: str | None = None
    role: ShopRole
    account_status: Literal["active", "disabled", "suspended"]
    membership_active: bool


class ShopEventRead(BaseModel):
    id: int
    shop_id: int
    event_type: str
    actor_user_account_id: int | None = None
    actor_name: str | None = None
    event_metadata: dict | None = None
    created_at: datetime


class WorkflowGapSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkflowGapStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    PLANNED = "planned"
    RESOLVED = "resolved"
    WONT_FIX = "wont_fix"


class WorkflowGapCreate(BaseModel):
    title: NonBlank = Field(max_length=200)
    description: NonBlank = Field(max_length=8000)
    workflow_area: NonBlank = Field(max_length=80)
    severity: WorkflowGapSeverity = WorkflowGapSeverity.MEDIUM
    workaround: str | None = Field(default=None, max_length=8000)


class WorkflowGapUpdate(BaseModel):
    title: NonBlank | None = Field(default=None, max_length=200)
    description: NonBlank | None = Field(default=None, max_length=8000)
    workflow_area: NonBlank | None = Field(default=None, max_length=80)
    severity: WorkflowGapSeverity | None = None
    status: WorkflowGapStatus | None = None
    workaround: str | None = Field(default=None, max_length=8000)


class WorkflowGapRead(BaseModel):
    id: int
    title: str
    description: str
    workflow_area: str
    severity: WorkflowGapSeverity
    status: WorkflowGapStatus
    workaround: str | None = None
    occurrence_count: int
    created_by_user_account_id: int | None = None
    updated_by_user_account_id: int | None = None
    first_reported_at: datetime
    last_reported_at: datetime
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkflowGapListResponse(BaseModel):
    items: list[WorkflowGapRead]
    page: int
    page_size: int
    total: int
    has_more: bool


class WorkflowGapEventRead(BaseModel):
    id: int
    event_type: Literal["created", "updated", "status_changed", "occurrence_recorded"]
    actor_user_account_id: int | None = None
    actor_name: str | None = None
    from_status: WorkflowGapStatus | None = None
    to_status: WorkflowGapStatus | None = None
    event_metadata: dict | None = None
    created_at: datetime


class WorkflowGapEventsResponse(BaseModel):
    items: list[WorkflowGapEventRead]


class SubscriptionTier(StrEnum):
    SOLO = "solo"
    TEAM = "team"
    SHOP = "shop"


class SubscriptionBillingStatus(StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class SubscriptionRead(BaseModel):
    tier: SubscriptionTier
    billing_status: SubscriptionBillingStatus
    seat_limit: int | None = None
    seats_used: int
    trial_ends_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    grace_period_ends_at: datetime | None = None
    canceled_at: datetime | None = None
    has_payment_method: bool
    is_access_suspended: bool
    shop_status: str


class SubscribeRequest(BaseModel):
    tier: SubscriptionTier


class AddPaymentMethodRequest(BaseModel):
    # The raw card number never reaches this backend -- `source_id` is a
    # single-use, already-tokenized nonce from Square's card-capture flow
    # (see docs/context/SECURITY.md's note on this sandbox-only slice: a
    # production-ready embedded card form needs its own CSP/architecture
    # decision, so this phase accepts Square's documented sandbox test
    # nonce rather than a real Web Payments SDK integration).
    source_id: NonBlank = Field(max_length=120)


class SubscriptionEventRead(BaseModel):
    id: int
    event_type: str
    actor_name: str | None = None
    event_metadata: dict | None = None
    created_at: datetime


class SubscriptionEventsResponse(BaseModel):
    items: list[SubscriptionEventRead]


class SupportShopSummary(BaseModel):
    shop_id: int
    display_name: str
    status: str
    created_at: datetime
    owner_username: str | None = None
    owner_display_name: str | None = None
    member_count: int
    subscription_tier: str | None = None
    subscription_billing_status: str | None = None
    seat_limit: int | None = None
    seats_used: int
    trial_ends_at: datetime | None = None
    is_access_suspended: bool


class SupportShopListResponse(BaseModel):
    items: list[SupportShopSummary]


class OperatingMode(StrEnum):
    """ADR-022: workflow-shaping axis, deliberately separate from
    `SubscriptionTier` (a commercial-entitlement axis). Values match
    `shops.operating_mode`'s check constraint exactly."""

    SOLO = "solo"
    MOBILE_FIELD = "mobile_field"
    SHOP = "shop"


class CapabilityId(StrEnum):
    """ADR-022 §2 capability-matrix row identifiers. Identifiers only --
    this foundation resolves availability, it does not enforce or hide
    anything (see app/capability_store.py)."""

    CUSTOMERS = "customers"
    VEHICLES = "vehicles"
    ESTIMATES = "estimates"
    DIAGNOSTICS = "diagnostics"
    WORK_ORDERS = "work_orders"
    INVOICES = "invoices"
    SCHEDULING = "scheduling"
    BAYS = "bays"
    TECHNICIANS = "technicians"
    PARTS = "parts"
    REPORTS = "reports"
    FIELD_FUNCTIONS = "field_functions"
    OPTIMUS_ACTIONS = "optimus_actions"


class CapabilityLevel(StrEnum):
    """Matches the ADR-022 §2 matrix legend exactly: `full` = primary
    workflow surface, `limited` = present but reduced, `hidden` = not
    surfaced by default but never deleted (ADR-022 Decision §4),
    `not_applicable` = the domain doesn't apply to this mode/role at all."""

    FULL = "full"
    LIMITED = "limited"
    HIDDEN = "hidden"
    NOT_APPLICABLE = "not_applicable"


class CapabilityEntry(BaseModel):
    id: CapabilityId
    level: CapabilityLevel


class CapabilitiesRead(BaseModel):
    """Read-only resolution snapshot. No enforcement: every existing route
    remains reachable regardless of this response's contents (ADR-022
    Decision §5, capability-foundation slice)."""

    operating_mode: OperatingMode
    tier: SubscriptionTier
    role: str
    seat_limit: int | None = None
    seats_used: int
    capabilities: list[CapabilityEntry]
    overrides_applied: list[str] = []
    resolved_at: datetime


class ModeTransitionCapabilityChange(BaseModel):
    """One capability whose level differs between the current and proposed
    operating mode."""

    id: CapabilityId
    from_level: CapabilityLevel
    to_level: CapabilityLevel


class ModeTransitionWarning(BaseModel):
    """A heads-up that existing data in a category will stop being surfaced
    by default under the proposed mode. The data is always retained (see
    `no_data_deleted`); this only flags that it will be hidden, so the owner
    makes the change deliberately."""

    category: str
    count: int
    from_level: CapabilityLevel
    to_level: CapabilityLevel
    message: str


class ModeTransitionPreviewRequest(BaseModel):
    proposed_mode: OperatingMode


class ModeTransitionPreview(BaseModel):
    """Read-only projection of what changing to `proposed_mode` would do.
    Computes nothing durable and mutates no data -- purely a dry run so an
    owner/manager can see the effect before applying it."""

    current_mode: OperatingMode
    proposed_mode: OperatingMode
    is_noop: bool
    capability_changes: list[ModeTransitionCapabilityChange]
    would_be_hidden: list[CapabilityId]
    retained_data_categories: list[str]
    warnings: list[ModeTransitionWarning]
    no_data_deleted: bool = True
    data_handling_statement: str


class ModeTransitionApplyRequest(BaseModel):
    # Optimistic concurrency: the client must state the mode it believes is
    # current. If the shop's real mode has since changed (another
    # owner/manager, another tab), the apply is rejected as stale rather
    # than silently clobbering the newer value.
    expected_current_mode: OperatingMode
    proposed_mode: OperatingMode


class ModeTransitionResult(BaseModel):
    """Result of a successful apply: what changed, plus the fresh capability
    snapshot so the caller does not need a second round-trip to
    GET /api/capabilities."""

    previous_mode: OperatingMode
    new_mode: OperatingMode
    changed: bool
    capability_changes: list[ModeTransitionCapabilityChange]
    capabilities: CapabilitiesRead


class ModeOnboardingStatus(BaseModel):
    """Owner-only read of whether a shop still needs its one-time post-signup
    operating-mode selection. `needs_onboarding` is true only while the shop
    has never confirmed a mode (a brand-new shop); backfilled/established
    shops return false and never see the first-run card."""

    needs_onboarding: bool
    operating_mode: OperatingMode
    confirmed_at: datetime | None = None


class ModeOnboardingCompleteRequest(BaseModel):
    # Optimistic concurrency, identical to the Settings apply: the client
    # states the mode it believes is current; a stale value returns 409.
    expected_current_mode: OperatingMode
    proposed_mode: OperatingMode


class ModeOnboardingResult(BaseModel):
    """Result of completing post-signup onboarding: the confirmation is now
    recorded (`confirmed_at`), what changed, and the fresh capability snapshot
    so the client can refresh nav without a second round-trip."""

    previous_mode: OperatingMode
    new_mode: OperatingMode
    changed: bool
    confirmed_at: datetime
    capability_changes: list[ModeTransitionCapabilityChange]
    capabilities: CapabilitiesRead


# --- Phase 2A: read-only host-disk / Docker-storage observability -------------
# Response models for GET /api/operations/storage. All fields are aggregate,
# non-sensitive metrics: byte totals, counts, percentages, enum states, a
# non-sensitive target label, and timing -- never the raw configured host
# path, container/image/volume names, secrets, or raw environment values.


class DiskUsageRead(BaseModel):
    # No path field -- the raw filesystem path is intentionally never exposed;
    # the top-level `target` label identifies what was measured.
    total_bytes: int | None
    used_bytes: int | None
    available_bytes: int | None
    used_percent: float | None
    status: DiskThresholdStatus


class DockerCategoryUsageRead(BaseModel):
    category: DockerCategory
    count: int | None
    size_bytes: int | None
    reclaimable_bytes: int | None


class DockerStorageRead(BaseModel):
    # "available" (df queried and parsed, even if all-zero) vs "unavailable"
    # (docker missing/unreachable/error) -- a healthy empty host is never
    # reported as unavailable.
    availability: DockerAvailability
    reason: str | None
    categories: list[DockerCategoryUsageRead]


class DiskThresholdsRead(BaseModel):
    warning_percent: float
    critical_percent: float


class StorageObservabilityRead(BaseModel):
    # Non-sensitive label for the measured filesystem (e.g.
    # "application_filesystem"); the raw path is never included.
    target: str
    # Bounded-collection metadata: whether this was freshly collected, served
    # from cache, or served stale, plus when it was collected and its age.
    freshness: Freshness
    collected_at: datetime
    age_seconds: float
    disk: DiskUsageRead
    docker: DockerStorageRead
    thresholds: DiskThresholdsRead


# --- Phase 2B: bounded runtime observability ---------------------------------
# Response models for GET /api/operations/summary. Every field is an aggregate,
# non-sensitive operational metric: counts, byte/latency aggregates, ages,
# fixed enum statuses, and static route templates ({param} placeholders only) --
# never a raw path/URL, id, username, email, shop/customer name, token, cookie,
# raw exception, SQL, env value, or any Docker/queue payload.


class RouteTrafficRead(BaseModel):
    # `route` is a static route template (e.g. "/api/customers/{customer_id}")
    # or a fixed sentinel ("<unmatched>"/"<other>") -- never a concrete path.
    method: str
    route: str
    count: int
    error_count: int
    average_latency_ms: float
    max_latency_ms: float


class RequestTrafficRead(BaseModel):
    uptime_seconds: float
    total_requests: int
    # Fixed status-class keys: informational/success/redirect/client_error/
    # server_error/other -> cumulative counts.
    status_classes: dict[str, int]
    average_latency_ms: float
    max_latency_ms: float
    tracked_routes: int
    label_overflow: bool
    top_routes: list[RouteTrafficRead]


class DependencyStatusRead(BaseModel):
    postgres: DependencyStatus
    redis: DependencyStatus


class WorkerHeartbeatRead(BaseModel):
    status: WorkerHeartbeatStatus
    # None unless status is alive/stale.
    age_seconds: float | None
    ttl_seconds: int


class QueueConditionRead(BaseModel):
    # "not_configured" (the default -- no application work queue exists today),
    # "idle"/"backlog" (a configured Redis list was read), or "unknown".
    status: QueueStatus
    depth: int | None


class CapabilityObserveCountersRead(BaseModel):
    # OBSERVE-only cumulative decision counts; carries no enforcement semantics.
    total: int
    decisions: dict[str, int]


class StorageSummaryRead(BaseModel):
    # Reuses the Phase 2A storage snapshot WITHOUT re-collecting. "not_collected"
    # means the dedicated /api/operations/storage endpoint has not populated the
    # cache yet (the summary never launches a Docker subprocess itself).
    status: Literal["collected", "not_collected"]
    freshness: Freshness | None
    collected_at: datetime | None
    age_seconds: float | None
    disk_status: DiskThresholdStatus | None
    docker_availability: DockerAvailability | None


class OperationsSummaryRead(BaseModel):
    # Fixed scope label: this summarizes the running application process, not the
    # production host.
    scope: str
    generated_at: datetime
    # Bounded-collection metadata for the runtime signals (dependencies/worker/
    # queue), which are served from a TTL cache with single-flight collection.
    freshness: Freshness
    collected_at: datetime
    age_seconds: float
    requests: RequestTrafficRead
    dependencies: DependencyStatusRead
    worker: WorkerHeartbeatRead
    queue: QueueConditionRead
    capabilities: CapabilityObserveCountersRead
    storage: StorageSummaryRead
