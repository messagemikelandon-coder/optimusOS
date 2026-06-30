from __future__ import annotations

from app.models import (
    Availability,
    Confidence,
    DecodedVehicle,
    EstimateRequest,
    LaborResearch,
    LocationInput,
    PartOption,
    PartRequirement,
    PartsResearch,
    ResearchBundle,
    ResolvedLocation,
    VehicleInput,
)
from app.services.estimator import EstimateService, choose_part


def option(*, price: float, availability: Availability, retailer: str = "AutoZone") -> PartOption:
    return PartOption(
        retailer=retailer,
        unit_price=price,
        availability=availability,
        url="https://www.autozone.com/test",
        confidence=Confidence.MEDIUM,
    )


def test_prefers_confirmed_stock_over_lower_unknown_price() -> None:
    selected = choose_part(
        [
            option(price=50, availability=Availability.UNKNOWN),
            option(price=70, availability=Availability.CONFIRMED_IN_STOCK),
        ]
    )
    assert selected is not None
    assert selected.unit_price == 70


def test_estimate_math(settings) -> None:  # type: ignore[no-untyped-def]
    request = EstimateRequest(
        vehicle=VehicleInput(year=2018, make="Honda", model="CR-V"),
        job="Replace front brake pads and rotors",
        location=LocationInput(postal_code="66442"),
    )
    research = ResearchBundle(
        labor=LaborResearch(
            book_hours=2.5,
            practical_hours_low=2.5,
            practical_hours_high=3.5,
            confidence=Confidence.MEDIUM,
            basis="Fixture",
        ),
        parts=PartsResearch(
            requirements=[
                PartRequirement(
                    part_name="Brake pad set",
                    quantity=1,
                    options=[option(price=60, availability=Availability.CONFIRMED_IN_STOCK)],
                ),
                PartRequirement(
                    part_name="Brake rotor",
                    quantity=2,
                    options=[option(price=80, availability=Availability.CONFIRMED_IN_STOCK)],
                ),
            ]
        ),
        summary="Fixture research",
    )
    result = EstimateService(settings).build(
        request=request,
        vehicle=DecodedVehicle(year=2018, make="Honda", model="CR-V"),
        location=ResolvedLocation(postal_code="66442"),
        research=research,
    )
    assert result.totals.labor_total == 250.00
    assert result.totals.parts_subtotal == 220.00
    assert result.totals.shop_supplies == 12.50
    assert result.totals.parts_tax == 18.70
    assert result.totals.mobile_service_fee == 25.00
    assert result.totals.estimated_total == 526.20


def test_missing_required_part_adds_warning(settings) -> None:  # type: ignore[no-untyped-def]
    request = EstimateRequest(
        vehicle=VehicleInput(year=2020, make="Dodge", model="Charger"),
        job="Replace starter",
        location=LocationInput(postal_code="66442"),
    )
    research = ResearchBundle(
        labor=LaborResearch(
            book_hours=1,
            practical_hours_low=1,
            practical_hours_high=2,
            confidence=Confidence.LOW,
            basis="Fixture",
        ),
        parts=PartsResearch(
            requirements=[PartRequirement(part_name="Starter", required=True, options=[])]
        ),
        summary="Fixture",
    )
    result = EstimateService(settings).build(
        request=request,
        vehicle=DecodedVehicle(year=2020, make="Dodge", model="Charger"),
        location=ResolvedLocation(postal_code="66442"),
        research=research,
    )
    assert any("Starter" in warning for warning in result.research.warnings)


def test_link_only_option_is_not_used_in_totals(settings) -> None:  # type: ignore[no-untyped-def]
    request = EstimateRequest(
        vehicle=VehicleInput(year=2020, make="Dodge", model="Challenger"),
        job="Replace starter",
        location=LocationInput(postal_code="95677"),
    )
    research = ResearchBundle(
        labor=LaborResearch(
            book_hours=1.0,
            practical_hours_low=1.0,
            practical_hours_high=2.0,
            confidence=Confidence.MEDIUM,
            basis="Fixture",
        ),
        parts=PartsResearch(
            requirements=[
                PartRequirement(
                    part_name="Starter",
                    options=[
                        PartOption(
                            retailer="Dealer",
                            unit_price=None,
                            availability=Availability.UNKNOWN,
                            url="https://parts.example.com/starter",
                        )
                    ],
                )
            ]
        ),
        summary="Link-only fixture",
    )
    result = EstimateService(settings).build(
        request=request,
        vehicle=DecodedVehicle(year=2020, make="Dodge", model="Challenger"),
        location=ResolvedLocation(postal_code="95677"),
        research=research,
    )
    assert result.totals.parts_subtotal == 0
    assert result.selected_parts == []
    assert any("Starter" in warning for warning in result.research.warnings)


def test_prefers_higher_confidence_price_before_stock_rank() -> None:
    low_confidence_stock = PartOption(
        retailer="Unknown seller",
        unit_price=40,
        availability=Availability.CONFIRMED_IN_STOCK,
        url="https://example.com/low",
        confidence=Confidence.LOW,
    )
    medium_confidence_unknown = PartOption(
        retailer="NAPA",
        unit_price=65,
        availability=Availability.UNKNOWN,
        url="https://www.napaonline.com/high",
        confidence=Confidence.MEDIUM,
    )
    selected = choose_part([low_confidence_stock, medium_confidence_unknown])
    assert selected is medium_confidence_unknown


def test_low_confidence_selected_price_adds_verification_warning(settings) -> None:  # type: ignore[no-untyped-def]
    request = EstimateRequest(
        vehicle=VehicleInput(year=2016, make="Nissan", model="Frontier"),
        job="Replace starter",
        location=LocationInput(postal_code="95677"),
    )
    research = ResearchBundle(
        labor=LaborResearch(
            book_hours=1.5,
            practical_hours_low=1.5,
            practical_hours_high=2.5,
            confidence=Confidence.MEDIUM,
            basis="Fixture",
        ),
        parts=PartsResearch(
            requirements=[
                PartRequirement(
                    part_name="Starter",
                    options=[
                        PartOption(
                            retailer="Retailer",
                            unit_price=200,
                            availability=Availability.UNKNOWN,
                            url="https://example.com/starter",
                            confidence=Confidence.LOW,
                        )
                    ],
                )
            ]
        ),
        summary="Fixture",
    )
    result = EstimateService(settings).build(
        request=request,
        vehicle=DecodedVehicle(year=2016, make="Nissan", model="Frontier"),
        location=ResolvedLocation(postal_code="95677"),
        research=research,
    )
    assert any("Low-confidence price evidence" in warning for warning in result.research.warnings)
