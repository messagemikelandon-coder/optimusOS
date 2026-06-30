from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.config import Settings
from app.models import (
    Availability,
    Confidence,
    DecodedVehicle,
    EstimateRequest,
    EstimateResponse,
    EstimateTotals,
    PartOption,
    ResearchBundle,
    ResolvedLocation,
    SelectedPart,
)
from app.security import availability_rank

MONEY = Decimal("0.01")
HOURS = Decimal("0.1")


def _money(value: float | Decimal) -> float:
    return float(Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP))


def _hours(value: float | Decimal) -> float:
    return float(Decimal(str(value)).quantize(HOURS, rounding=ROUND_HALF_UP))


def choose_part(options: list[PartOption]) -> PartOption | None:
    usable = [
        option
        for option in options
        if option.availability != Availability.OUT_OF_STOCK and option.unit_price is not None
    ]
    if not usable:
        return None
    confidence_rank = {
        Confidence.HIGH: 0,
        Confidence.MEDIUM: 1,
        Confidence.LOW: 2,
    }
    return min(
        usable,
        key=lambda option: (
            confidence_rank[option.confidence],
            availability_rank(option.availability),
            option.unit_price if option.unit_price is not None else float("inf"),
            option.store_distance_miles if option.store_distance_miles is not None else 10_000,
        ),
    )


class EstimateService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def build(
        self,
        *,
        request: EstimateRequest,
        vehicle: DecodedVehicle,
        location: ResolvedLocation,
        research: ResearchBundle,
    ) -> EstimateResponse:
        labor_rate = request.labor_rate if request.labor_rate is not None else self._settings.labor_rate
        mobile_fee = (
            request.mobile_service_fee
            if request.mobile_service_fee is not None
            else self._settings.mobile_service_fee
        )
        supplies_percent = (
            request.shop_supplies_percent
            if request.shop_supplies_percent is not None
            else self._settings.shop_supplies_percent
        )
        parts_tax_rate = (
            request.parts_tax_rate
            if request.parts_tax_rate is not None
            else self._settings.parts_tax_rate
        )

        selected_parts: list[SelectedPart] = []
        for requirement in research.parts.requirements:
            selected = choose_part(requirement.options)
            if selected is None:
                continue
            if selected.unit_price is None:
                raise RuntimeError("Part selection returned an option without a price.")
            extended = _money(selected.unit_price * requirement.quantity)
            selected_parts.append(
                SelectedPart(
                    part_name=requirement.part_name,
                    quantity=requirement.quantity,
                    retailer=selected.retailer,
                    brand=selected.brand,
                    part_number=selected.part_number,
                    unit_price=_money(selected.unit_price),
                    extended_price=extended,
                    availability=selected.availability,
                    store_name=selected.store_name,
                    url=selected.url,
                    confidence=selected.confidence,
                )
            )

        labor_hours = _hours(research.labor.book_hours)
        labor_total = _money(labor_hours * labor_rate)
        parts_subtotal = _money(sum(part.extended_price for part in selected_parts))
        shop_supplies = _money(labor_total * (supplies_percent / 100))
        parts_tax = _money(parts_subtotal * (parts_tax_rate / 100))
        estimated_total = _money(
            labor_total + parts_subtotal + shop_supplies + mobile_fee + parts_tax
        )

        warnings = list(research.warnings)
        missing_required = [
            requirement.part_name
            for requirement in research.parts.requirements
            if requirement.required and choose_part(requirement.options) is None
        ]
        if missing_required:
            warnings.append(
                "No usable priced option was found for required part(s): " + ", ".join(missing_required)
            )
        low_confidence_selected = [
            part.part_name for part in selected_parts if part.confidence == Confidence.LOW
        ]
        if low_confidence_selected:
            warnings.append(
                "Low-confidence price evidence was used for: "
                + ", ".join(low_confidence_selected)
                + ". Verify before quoting the customer."
            )
        if parts_tax_rate == 0:
            warnings.append("Sales tax is excluded because PARTS_TAX_RATE is 0.00.")

        updated_research = research.model_copy(update={"warnings": list(dict.fromkeys(warnings))})

        return EstimateResponse(
            vehicle=vehicle,
            location=location,
            job=request.job,
            research=updated_research,
            selected_parts=selected_parts,
            totals=EstimateTotals(
                labor_hours=labor_hours,
                labor_rate=_money(labor_rate),
                labor_total=labor_total,
                parts_subtotal=parts_subtotal,
                shop_supplies=shop_supplies,
                mobile_service_fee=_money(mobile_fee),
                parts_tax=parts_tax,
                estimated_total=estimated_total,
                practical_time_low=_hours(research.labor.practical_hours_low),
                practical_time_high=_hours(research.labor.practical_hours_high),
            ),
            generated_at_utc=datetime.now(UTC).isoformat(),
        )
