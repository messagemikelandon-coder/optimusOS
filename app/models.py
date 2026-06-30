from __future__ import annotations

import re
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
            raise ValueError("VIN must contain 11-17 valid letters and digits and cannot contain I, O, or Q.")
        return cleaned

    @model_validator(mode="after")
    def require_vin_or_vehicle(self) -> VehicleInput:
        if not self.vin and not (self.year and self.make and self.model):
            raise ValueError("Provide a VIN or year, make, and model.")
        return self

    def display_name(self) -> str:
        parts = [str(self.year) if self.year else None, self.make, self.model, self.trim, self.engine]
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
        parts = [str(self.year) if self.year else None, self.make, self.model, self.trim, self.engine]
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
