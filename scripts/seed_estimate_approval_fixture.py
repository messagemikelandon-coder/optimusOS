from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta

from pydantic import HttpUrl
from sqlalchemy import select

from app.config import get_settings
from app.customer_store import display_name as customer_display_name
from app.db import build_session_factory
from app.db_models import Customer, Estimate, EstimateRevision, UserAccount, Vehicle
from app.estimate_store import _canonical_hash
from app.models import (
    Availability,
    Confidence,
    DecodedVehicle,
    EstimatePaymentOption,
    EstimatePaymentOptionCode,
    EstimateRequest,
    EstimateResponse,
    EstimateStatus,
    LaborResearch,
    LocationInput,
    PartOption,
    PartRequirement,
    PartsResearch,
    ResearchBundle,
    ResolvedLocation,
    VehicleInput,
)
from app.services.estimator import EstimateService
from app.shop_store import resolve_shop_id_for_owner
from app.vehicle_store import vehicle_display_name


def build_valid_response(settings) -> tuple[EstimateRequest, EstimateResponse]:
    request = EstimateRequest(
        vehicle=VehicleInput(
            year=2018,
            make="Honda",
            model="Civic",
            trim="EX",
            engine="2.0L I4",
            drivetrain="FWD",
        ),
        job="Replace front brake pads and front brake rotors, inspect hardware, and road test the vehicle.",
        location=LocationInput(postal_code="95677"),
        labor_rate=100,
        mobile_service_fee=35,
        shop_supplies_percent=5,
        parts_tax_rate=8.25,
    )
    research = ResearchBundle(
        labor=LaborResearch(
            book_hours=2.5,
            practical_hours_low=2.5,
            practical_hours_high=3.0,
            confidence=Confidence.MEDIUM,
            basis="Deterministic non-billable fixture.",
        ),
        parts=PartsResearch(
            requirements=[
                PartRequirement(
                    part_name="Front brake pad set",
                    quantity=1,
                    options=[
                        PartOption(
                            retailer="NAPA",
                            brand="NAPA Premium",
                            part_number="PAD-2018-CIVIC",
                            unit_price=120,
                            availability=Availability.CONFIRMED_IN_STOCK,
                            store_name="NAPA Rocklin",
                            store_distance_miles=4.2,
                            url=HttpUrl("https://example.com/pad-set"),
                            confidence=Confidence.MEDIUM,
                        ),
                        # A higher-priced competing option that `choose_part`
                        # must not select. It exists only to prove the public
                        # approval view never leaks unselected competing-
                        # retailer research options (Fix 4 narrowing).
                        PartOption(
                            retailer="AutoZone",
                            brand="Duralast",
                            part_number="UNSELECTED-COMPETITOR-PAD-999",
                            unit_price=225,
                            availability=Availability.CONFIRMED_IN_STOCK,
                            store_name="AutoZone Rocklin",
                            store_distance_miles=6.0,
                            url=HttpUrl("https://example.com/competitor-pad-option"),
                            confidence=Confidence.MEDIUM,
                        ),
                    ],
                ),
                PartRequirement(
                    part_name="Front brake rotor",
                    quantity=2,
                    options=[
                        PartOption(
                            retailer="NAPA",
                            brand="NAPA Premium",
                            part_number="ROTOR-2018-CIVIC",
                            unit_price=85,
                            availability=Availability.CONFIRMED_IN_STOCK,
                            store_name="NAPA Rocklin",
                            store_distance_miles=4.2,
                            url=HttpUrl("https://example.com/rotor"),
                            confidence=Confidence.MEDIUM,
                        )
                    ],
                ),
            ]
        ),
        summary="Deterministic fixture estimate for non-billable approval verification.",
        warnings=["Synthetic fixture for approval-route verification."],
    )
    response = EstimateService(settings).build(
        request=request,
        vehicle=DecodedVehicle(
            year=2018,
            make="Honda",
            model="Civic",
            trim="EX",
            engine="2.0L I4",
            drivetrain="FWD",
        ),
        location=ResolvedLocation(postal_code="95677", city="Rocklin", region="CA", country="US"),
        research=research,
    )
    return request, response


def build_zero_response() -> tuple[EstimateRequest, EstimateResponse]:
    request = EstimateRequest(
        vehicle=VehicleInput(
            year=2018,
            make="Honda",
            model="Civic",
        ),
        job="Replace front brake pads and front brake rotors, inspect hardware, and road test the vehicle.",
        location=LocationInput(postal_code="95677"),
        labor_rate=100,
        mobile_service_fee=0,
        shop_supplies_percent=0,
        parts_tax_rate=0,
    )
    response = EstimateResponse.model_validate(
        {
            "vehicle": {"year": 2018, "make": "Honda", "model": "Civic"},
            "location": {
                "postal_code": "95677",
                "city": "Rocklin",
                "region": "CA",
                "country": "US",
            },
            "job": request.job,
            "research": {
                "labor": {
                    "book_hours": 0,
                    "practical_hours_low": 0,
                    "practical_hours_high": 0,
                    "confidence": "low",
                    "basis": "Broken zero-value fixture.",
                    "special_tools": [],
                    "risk_flags": [],
                },
                "parts": {
                    "requirements": [
                        {
                            "part_name": "Front brake pad set",
                            "quantity": 1,
                            "required": True,
                            "options": [],
                        }
                    ],
                    "notes": [],
                },
                "summary": "Narrative-only broken fixture.",
                "warnings": ["Broken zero-value fixture."],
            },
            "labor_items": [],
            "selected_parts": [],
            "fee_items": [
                {"code": "shop_supplies", "label": "Shop supplies", "amount": 0},
                {"code": "mobile_service_fee", "label": "Mobile service charge", "amount": 0},
                {"code": "parts_tax", "label": "Parts tax", "amount": 0},
            ],
            "totals": {
                "labor_hours": 0,
                "labor_rate": 100,
                "labor_total": 0,
                "parts_subtotal": 0,
                "shop_supplies": 0,
                "mobile_service_fee": 0,
                "parts_tax": 0,
                "estimated_total": 0,
                "practical_time_low": 0,
                "practical_time_high": 0,
            },
            "generated_at_utc": datetime.now(UTC).isoformat(),
        }
    )
    return request, response


def payment_options() -> list[EstimatePaymentOption]:
    return [
        EstimatePaymentOption(
            code=EstimatePaymentOptionCode.PAY_IN_FULL,
            label="Pay in full",
            description="Pay the full approved amount when service is complete.",
        ),
        EstimatePaymentOption(
            code=EstimatePaymentOptionCode.TWO_MONTH_PLAN,
            label="Two-month plan",
            description=(
                "Parts-price deposit is due before parts are ordered. No repair begins until deposit "
                "and authorization are complete. Remaining payments are due 30 and 60 days after service."
            ),
            requires_payment_plan_acknowledgement=True,
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zero-total", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    session = build_session_factory(settings.database_url)()
    try:
        owner = session.scalar(
            select(UserAccount).where(UserAccount.username == settings.optimus_owner_username)
        )
        if owner is None:
            raise RuntimeError("Owner account was not found.")
        shop_id = resolve_shop_id_for_owner(session, owner.id)

        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        customer = Customer(
            owner_user_id=owner.id,
            shop_id=shop_id,
            first_name="Fixture",
            last_name=f"Approval {stamp}",
            email=f"fixture-{stamp}@example.test",
            phone="555-0112",
            city="Rocklin",
            state="CA",
            postal_code="95677",
        )
        session.add(customer)
        session.flush()
        vehicle = Vehicle(
            owner_user_id=owner.id,
            shop_id=shop_id,
            customer_id=customer.id,
            year=2018,
            make="Honda",
            model="Civic",
            trim="EX",
            engine="2.0L I4",
            drivetrain="FWD",
            license_plate=f"FX{stamp[-6:]}",
            license_plate_state="CA",
            current_mileage=125432,
        )
        session.add(vehicle)
        session.flush()

        request_model, response_model = (
            build_zero_response() if args.zero_total else build_valid_response(settings)
        )
        approval_due_at = datetime.now(UTC) + timedelta(days=7)
        estimate = Estimate(
            owner_user_id=owner.id,
            shop_id=shop_id,
            customer_id=customer.id,
            vehicle_id=vehicle.id,
            estimate_number=f"EST-{owner.id:03d}-FIX-{stamp[-6:]}",
            status=EstimateStatus.READY.value,
            current_revision_number=1,
            estimate_total=response_model.totals.estimated_total,
            expires_at=approval_due_at,
            is_archived=False,
        )
        session.add(estimate)
        session.flush()
        snapshot = {
            "customer": {
                "id": customer.id,
                "display_name": customer_display_name(customer),
                "email": customer.email,
                "phone": customer.phone,
            },
            "vehicle": {
                "id": vehicle.id,
                "customer_id": customer.id,
                "display_name": vehicle_display_name(vehicle),
                "vin": vehicle.vin,
                "license_plate": vehicle.license_plate,
                "current_mileage": vehicle.current_mileage,
            },
            "request": request_model.model_dump(mode="json"),
            "estimate": response_model.model_dump(mode="json"),
            "terms_text": (
                "Approval authorizes the quoted work only. Additional material changes require a new revision. "
                "Parts-price deposits are due before parts are ordered."
            ),
            "payment_options": [item.model_dump(mode="json") for item in payment_options()],
            "approval_due_at": approval_due_at.isoformat(),
        }
        revision = EstimateRevision(
            estimate_id=estimate.id,
            owner_user_id=owner.id,
            shop_id=shop_id,
            revision_number=1,
            status=EstimateStatus.READY.value,
            customer_snapshot=snapshot["customer"],
            vehicle_snapshot=snapshot["vehicle"],
            estimate_request_payload=snapshot["request"],
            estimate_response_payload=snapshot["estimate"],
            terms_text=snapshot["terms_text"],
            payment_options_payload=snapshot["payment_options"],
            approval_due_at=approval_due_at,
            content_hash=_canonical_hash(snapshot),
        )
        session.add(revision)
        session.commit()
        print(
            json.dumps(
                {
                    "customer_id": customer.id,
                    "customer_display_name": customer_display_name(customer),
                    "vehicle_id": vehicle.id,
                    "vehicle_display_name": vehicle_display_name(vehicle),
                    "estimate_id": estimate.id,
                    "estimate_number": estimate.estimate_number,
                    "revision_number": 1,
                    "zero_total": args.zero_total,
                }
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
