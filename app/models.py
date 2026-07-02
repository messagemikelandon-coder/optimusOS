from __future__ import annotations

import re
from datetime import datetime
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

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


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
    selected_parts: list[SelectedPart]
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
    password: NonBlank = Field(min_length=8, max_length=256)


class AuthUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str


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
    terms_text: str = Field(default="Customer authorization is required before repair work begins.", max_length=4000)
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


class EstimateApprovalView(BaseModel):
    estimate_id: int
    estimate_number: str
    status: EstimateStatus
    revision: EstimateRevisionRead
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
    events: list[EstimateApprovalEventRead]


class WorkOrderBase(BaseModel):
    customer_id: int | None = None
    vehicle_id: int | None = None
    status: str = Field(default="open", max_length=40)
    title: NonBlank = Field(max_length=180)
    complaint: NonBlank = Field(max_length=10_000)
    diagnosis: str | None = Field(default=None, max_length=10_000)
    estimate_total: float | None = Field(default=None, ge=0, le=1_000_000)
    labor_hours_estimate: float | None = Field(default=None, ge=0, le=500)
    notes: str | None = Field(default=None, max_length=10_000)
    internal_notes: str | None = Field(default=None, max_length=10_000)


class WorkOrderCreate(WorkOrderBase):
    pass


class WorkOrderUpdate(BaseModel):
    customer_id: int | None = None
    vehicle_id: int | None = None
    status: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=180)
    complaint: str | None = Field(default=None, max_length=10_000)
    diagnosis: str | None = Field(default=None, max_length=10_000)
    estimate_total: float | None = Field(default=None, ge=0, le=1_000_000)
    labor_hours_estimate: float | None = Field(default=None, ge=0, le=500)
    notes: str | None = Field(default=None, max_length=10_000)
    internal_notes: str | None = Field(default=None, max_length=10_000)


class WorkOrderRead(WorkOrderBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    customer_name: str | None = None
    vehicle_name: str | None = None
    approval_status: str | None = None


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
