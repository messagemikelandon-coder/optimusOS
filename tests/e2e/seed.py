from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import get_settings
from app.customer_store import display_name as customer_display_name
from app.db_models import Customer, Estimate, EstimateRevision, Vehicle
from app.estimate_store import _canonical_hash
from app.models import EstimatePaymentOption, EstimatePaymentOptionCode, EstimateStatus
from app.vehicle_store import vehicle_display_name
from scripts.seed_estimate_approval_fixture import build_valid_response


def seed_ready_estimate(db: Session, *, owner_id: int, customer_id: int, vehicle_id: int) -> int:
    """Persists a real, complete, `ready`-status estimate + first revision
    directly via the ORM, reusing the exact deterministic (non-billable)
    research fixture already established in
    scripts/seed_estimate_approval_fixture.py for this repo's approval-route
    tests. This avoids a real, billable OpenAI research call for the one
    step of the core workflow (estimate research) that isn't reasonable to
    drive through the real UI in an automated E2E run -- every other step
    (customer, vehicle, approval, work order, invoice, payment) goes
    through the real browser and real API exactly as a user would.
    """
    settings = get_settings()
    customer = db.get(Customer, customer_id)
    vehicle = db.get(Vehicle, vehicle_id)
    if customer is None or vehicle is None:
        raise ValueError("customer_id/vehicle_id must reference existing rows.")

    _request_model, response_model = build_valid_response(settings)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    approval_due_at = datetime.now(UTC) + timedelta(days=7)

    estimate = Estimate(
        owner_user_id=owner_id,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        vehicle_id=vehicle.id,
        estimate_number=f"EST-{owner_id:03d}-E2E-{stamp[-8:]}",
        status=EstimateStatus.READY.value,
        current_revision_number=1,
        estimate_total=response_model.totals.estimated_total,
        expires_at=approval_due_at,
        is_archived=False,
    )
    db.add(estimate)
    db.flush()

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
        "request": _request_model.model_dump(mode="json"),
        "estimate": response_model.model_dump(mode="json"),
        "terms_text": (
            "Approval authorizes the quoted work only. Additional material changes "
            "require a new revision. Parts-price deposits are due before parts are ordered."
        ),
        "payment_options": [
            EstimatePaymentOption(
                code=EstimatePaymentOptionCode.PAY_IN_FULL,
                label="Pay in full",
                description="Pay the full approved amount when service is complete.",
            ).model_dump(mode="json")
        ],
        "approval_due_at": approval_due_at.isoformat(),
    }
    revision = EstimateRevision(
        estimate_id=estimate.id,
        owner_user_id=owner_id,
        shop_id=estimate.shop_id,
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
    db.add(revision)
    db.commit()
    return estimate.id
