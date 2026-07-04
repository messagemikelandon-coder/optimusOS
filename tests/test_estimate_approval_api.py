from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import HttpUrl
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.main as main
from app.auth import bootstrap_owner_account
from app.config import Settings
from app.db import Base, build_engine, build_session_factory
from app.db_models import Estimate, EstimateApprovalEvent, EstimateApprovalRequest, EstimateRevision
from app.models import (
    Availability,
    Confidence,
    DecodedVehicle,
    EstimateApprovalActionRequest,
    EstimateApprovalTokenRequest,
    EstimateCreate,
    EstimateDeclineActionRequest,
    EstimateFeeItem,
    EstimateLaborItem,
    EstimatePaymentOption,
    EstimatePaymentOptionCode,
    EstimateResponse,
    EstimateRevisionCreate,
    EstimateSendForApprovalRequest,
    EstimateStatus,
    EstimateTotals,
    EstimateUpdate,
    LaborResearch,
    LocationInput,
    PartOption,
    PartRequirement,
    PartsResearch,
    ResearchBundle,
    ResolvedLocation,
    SelectedPart,
)
from app.orchestrator import OptimusResearchOrchestrator
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_vehicles_api import create_customer_for_auth, vehicle_payload


def fixture_estimate_response() -> EstimateResponse:
    return EstimateResponse(
        vehicle=DecodedVehicle(
            vin="1HGCM82633A004352",
            year=2018,
            make="Honda",
            model="Civic",
            trim="EX",
            engine="2.0L I4",
            drivetrain="FWD",
        ),
        location=ResolvedLocation(postal_code="95677", city="Rocklin", region="CA", country="US"),
        job="Replace front brakes",
        research=ResearchBundle(
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
                        options=[
                            PartOption(
                                retailer="NAPA",
                                unit_price=120,
                                availability=Availability.CONFIRMED_IN_STOCK,
                                url=HttpUrl("https://example.com/pad-set"),
                                confidence=Confidence.MEDIUM,
                            )
                        ],
                    )
                ]
            ),
            summary="Fixture research bundle",
        ),
        labor_items=[
            EstimateLaborItem(
                description="Replace front brakes",
                labor_hours=2.5,
                labor_rate=100,
                labor_total=250,
            )
        ],
        selected_parts=[
            SelectedPart(
                part_name="Brake pad set",
                quantity=1,
                retailer="NAPA",
                brand="NAPA",
                part_number="PAD-1",
                unit_price=120,
                extended_price=120,
                availability=Availability.CONFIRMED_IN_STOCK,
                store_name="NAPA Rocklin",
                url=HttpUrl("https://example.com/pad-set"),
                confidence=Confidence.MEDIUM,
            )
        ],
        fee_items=[
            EstimateFeeItem(code="shop_supplies", label="Shop supplies", amount=12.5),
            EstimateFeeItem(code="mobile_service_fee", label="Mobile service charge", amount=25),
            EstimateFeeItem(code="parts_tax", label="Parts tax", amount=10.2),
        ],
        totals=EstimateTotals(
            labor_hours=2.5,
            labor_rate=100,
            labor_total=250,
            parts_subtotal=120,
            shop_supplies=12.5,
            mobile_service_fee=25,
            parts_tax=10.2,
            estimated_total=417.7,
            practical_time_low=2.5,
            practical_time_high=3.5,
        ),
        generated_at_utc=datetime.now(UTC).isoformat(),
    )


def fixture_estimate_response_with_sensitive_research() -> EstimateResponse:
    """Same as ``fixture_estimate_response`` but with additional internal
    research detail that must never reach the public approval-view endpoint:
    an unselected competing-retailer part option and internal labor
    reasoning (basis/special tools/risk flags)."""
    response = fixture_estimate_response().model_copy(deep=True)
    response.research.labor.basis = "INTERNAL-LABOR-BASIS-MARKER-7788"
    response.research.labor.special_tools = ["INTERNAL-SPECIAL-TOOL-MARKER-7788"]
    response.research.labor.risk_flags = ["INTERNAL-RISK-FLAG-MARKER-7788"]
    response.research.parts.requirements[0].options.append(
        PartOption(
            retailer="UNSELECTED-COMPETITOR-RETAILER-7788",
            unit_price=999,
            availability=Availability.CONFIRMED_IN_STOCK,
            url=HttpUrl("https://example.com/unselected-competitor-option"),
            confidence=Confidence.MEDIUM,
        )
    )
    return response


async def stub_sensitive_research_estimate_job(self, request):  # type: ignore[no-untyped-def]
    del self, request
    return fixture_estimate_response_with_sensitive_research()


def zero_value_estimate_response() -> EstimateResponse:
    return EstimateResponse(
        vehicle=DecodedVehicle(year=2018, make="Honda", model="Civic"),
        location=ResolvedLocation(postal_code="95677", city="Rocklin", region="CA", country="US"),
        job="Replace front brakes",
        research=ResearchBundle(
            labor=LaborResearch(
                book_hours=0,
                practical_hours_low=0,
                practical_hours_high=0,
                confidence=Confidence.LOW,
                basis="Incomplete fixture",
            ),
            parts=PartsResearch(
                requirements=[
                    PartRequirement(
                        part_name="Brake pad set",
                        quantity=1,
                        required=True,
                        options=[],
                    )
                ]
            ),
            summary="Narrative-only estimate mentioning prices without structured pricing.",
        ),
        labor_items=[],
        selected_parts=[],
        fee_items=[
            EstimateFeeItem(code="shop_supplies", label="Shop supplies", amount=0),
            EstimateFeeItem(code="mobile_service_fee", label="Mobile service charge", amount=0),
            EstimateFeeItem(code="parts_tax", label="Parts tax", amount=0),
        ],
        totals=EstimateTotals(
            labor_hours=0,
            labor_rate=100,
            labor_total=0,
            parts_subtotal=0,
            shop_supplies=0,
            mobile_service_fee=0,
            parts_tax=0,
            estimated_total=0,
            practical_time_low=0,
            practical_time_high=0,
        ),
        generated_at_utc=datetime.now(UTC).isoformat(),
    )


def partial_collapse_estimate_response() -> EstimateResponse:
    """Real, priced parts sitting next to a single fabricated zero-hour labor line."""
    response = fixture_estimate_response().model_copy(deep=True)
    response.labor_items = [
        EstimateLaborItem(
            description="Replace front brakes",
            labor_hours=0,
            labor_rate=100,
            labor_total=0,
        )
    ]
    response.totals.labor_hours = 0
    response.totals.labor_total = 0
    response.totals.estimated_total = 167.7
    return response


def parts_only_estimate_response() -> EstimateResponse:
    """A legitimate labor-optional job: explicitly no labor items, real parts pricing."""
    response = fixture_estimate_response().model_copy(deep=True)
    response.labor_items = []
    response.totals.labor_hours = 0
    response.totals.labor_rate = 100
    response.totals.labor_total = 0
    response.totals.estimated_total = 167.7
    return response


def forged_total_estimate_response() -> EstimateResponse:
    response = fixture_estimate_response().model_copy(deep=True)
    response.totals.estimated_total = 1
    return response


def negative_value_estimate_response() -> EstimateResponse:
    response = fixture_estimate_response().model_copy(deep=True)
    response.selected_parts[0].unit_price = -120
    response.selected_parts[0].extended_price = -120
    response.totals.parts_subtotal = -120
    response.totals.estimated_total = 177.7
    return response


async def stub_estimate_job(self, request):  # type: ignore[no-untyped-def]
    del self, request
    return fixture_estimate_response()


async def stub_zero_value_estimate_job(self, request):  # type: ignore[no-untyped-def]
    del self, request
    return zero_value_estimate_response()


async def stub_forged_total_estimate_job(self, request):  # type: ignore[no-untyped-def]
    del self, request
    return forged_total_estimate_response()


async def stub_negative_value_estimate_job(self, request):  # type: ignore[no-untyped-def]
    del self, request
    return negative_value_estimate_response()


async def stub_partial_collapse_estimate_job(self, request):  # type: ignore[no-untyped-def]
    del self, request
    return partial_collapse_estimate_response()


async def stub_parts_only_estimate_job(self, request):  # type: ignore[no-untyped-def]
    del self, request
    return parts_only_estimate_response()


def estimate_create_payload(customer_id: int, vehicle_id: int) -> EstimateCreate:
    return EstimateCreate(
        customer_id=customer_id,
        vehicle_id=vehicle_id,
        job="Replace front brakes",
        location=LocationInput(postal_code="95677"),
        terms_text="Customer must approve before work begins.",
        payment_options=[
            EstimatePaymentOption(
                code=EstimatePaymentOptionCode.PAY_IN_FULL,
                label="Pay in full",
                description="Pay when service is complete.",
            ),
            EstimatePaymentOption(
                code=EstimatePaymentOptionCode.TWO_MONTH_PLAN,
                label="Two-month plan",
                description="Deposit before parts. Balance due 30 and 60 days after service.",
                requires_payment_plan_acknowledgement=True,
            ),
        ],
        expires_in_days=7,
    )


async def create_estimate_for_auth(settings: Settings, db_session: Session, auth):  # type: ignore[no-untyped-def]
    customer_id = await create_customer_for_auth(settings, db_session, auth)
    vehicle = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)
    estimate = await main.create_estimate_record(
        estimate_create_payload(customer_id, vehicle.id),
        db_session,
        settings,
        auth,
    )
    return customer_id, vehicle, estimate


@pytest.mark.anyio
async def test_estimate_routes_require_authenticated_session(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/estimates"), db_session, settings)
    assert excinfo.value.status_code == 401


@pytest.mark.anyio
async def test_create_send_approve_and_audit_estimate(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, vehicle, estimate = await create_estimate_for_auth(settings, db_session, auth)

    assert estimate.status is EstimateStatus.DRAFT
    assert estimate.current_revision.estimate.totals.estimated_total == 417.7

    updated = await main.update_estimate_record(
        estimate.id,
        EstimateUpdate(status=EstimateStatus.READY),
        db_session,
        auth,
    )
    assert updated.status is EstimateStatus.READY

    sent = await main.send_estimate_record_for_approval(
        estimate.id,
        EstimateSendForApprovalRequest(),
        db_session,
        auth,
        request_for("/api/estimates/1/send-for-approval", method="POST"),
    )
    assert sent.status is EstimateStatus.AWAITING_APPROVAL
    token = sent.approval_link.split("#token=", 1)[1]

    approval_view = await main.approval_view(
        EstimateApprovalTokenRequest(token=token),
        db_session,
        request_for("/api/estimate-approval/view", method="POST"),
        settings,
    )
    assert approval_view.revision.vehicle.id == vehicle.id
    assert approval_view.revision.estimate.labor_items[0].description == "Replace front brakes"
    assert approval_view.revision.estimate.fee_items[0].code == "shop_supplies"

    approved = await main.approval_approve(
        EstimateApprovalActionRequest(
            token=token,
            revision_number=approval_view.revision.revision_number,
            approving_name="Jane Customer",
            accepted_terms=True,
            payment_option=EstimatePaymentOptionCode.TWO_MONTH_PLAN,
            payment_plan_acknowledged=True,
            typed_authorization="Jane Customer approves the estimate.",
        ),
        db_session,
        request_for("/api/estimate-approval/approve", method="POST"),
        settings,
    )
    assert approved.status is EstimateStatus.APPROVED

    locked = await main.get_estimate_record(estimate.id, db_session, auth)
    assert locked.status is EstimateStatus.APPROVED
    assert locked.payment_option_selected == EstimatePaymentOptionCode.TWO_MONTH_PLAN.value

    history = await main.estimate_approval_history(estimate.id, db_session, auth)
    assert [event.event_type for event in history.events] == ["sent", "approved"]
    assert history.events[-1].actor_name == "Jane Customer"
    assert history.events[-1].payment_plan_acknowledged is True


@pytest.mark.anyio
async def test_public_approval_view_excludes_internal_research_and_raw_overrides(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    """The unauthenticated, token-authenticated approval-view endpoint must
    never leak unselected competing-retailer part options, internal labor
    reasoning (basis/special tools/risk flags), or raw request rate/fee
    overrides, while still returning everything the customer needs."""
    monkeypatch.setattr(
        OptimusResearchOrchestrator, "estimate_job", stub_sensitive_research_estimate_job
    )
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)
    vehicle = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)
    estimate = await main.create_estimate_record(
        estimate_create_payload(customer_id, vehicle.id),
        db_session,
        settings,
        auth,
    )
    sent = await main.send_estimate_record_for_approval(
        estimate.id,
        EstimateSendForApprovalRequest(),
        db_session,
        auth,
        request_for("/api/estimates/1/send-for-approval", method="POST"),
    )
    token = sent.approval_link.split("#token=", 1)[1]

    approval_view = await main.approval_view(
        EstimateApprovalTokenRequest(token=token),
        db_session,
        request_for("/api/estimate-approval/view", method="POST"),
        settings,
    )
    payload = approval_view.model_dump(mode="json")
    body = json.dumps(payload)

    # Internal research reasoning and unselected competing options must not leak
    # anywhere in the serialized payload.
    assert "INTERNAL-LABOR-BASIS-MARKER-7788" not in body
    assert "INTERNAL-SPECIAL-TOOL-MARKER-7788" not in body
    assert "INTERNAL-RISK-FLAG-MARKER-7788" not in body
    assert "UNSELECTED-COMPETITOR-RETAILER-7788" not in body

    revision = payload["revision"]
    research = revision["estimate"]["research"]

    # The narrow research view exposes only summary/warnings: no parts
    # requirement/option research and no internal labor reasoning fields.
    assert set(research.keys()) == {"summary", "warnings"}

    # The internal generation request (which may carry raw labor rate, mobile
    # service fee, shop supplies percent, and parts tax rate overrides) must
    # not be present on the narrow revision view at all.
    assert "request" not in revision

    # Everything a customer needs to review and act on the estimate must remain.
    assert payload["estimate_number"] == estimate.estimate_number
    assert payload["token_expires_at"]
    assert revision["revision_number"] == 1
    assert revision["customer"]["display_name"]
    assert revision["vehicle"]["display_name"]
    assert revision["terms_text"] == "Customer must approve before work begins."
    assert len(revision["payment_options"]) == 2
    assert revision["estimate"]["labor_items"][0]["description"] == "Replace front brakes"
    assert revision["estimate"]["selected_parts"][0]["part_name"] == "Brake pad set"
    assert revision["estimate"]["fee_items"][0]["code"] == "shop_supplies"
    assert revision["estimate"]["totals"]["estimated_total"] == 417.7
    assert research["summary"] == "Fixture research bundle"


@pytest.mark.anyio
async def test_zero_value_estimate_is_rejected_before_persistence(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_zero_value_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)
    vehicle = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_estimate_record(
            estimate_create_payload(customer_id, vehicle.id),
            db_session,
            settings,
            auth,
        )
    assert excinfo.value.status_code == 422
    assert (
        "greater than zero" in str(excinfo.value.detail).lower()
        or "structured estimate generation failed" in str(excinfo.value.detail).lower()
    )
    assert db_session.scalar(select(Estimate)) is None


@pytest.mark.anyio
async def test_zero_value_estimate_cannot_be_sent_for_approval(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, _, estimate = await create_estimate_for_auth(settings, db_session, auth)
    revision = db_session.scalar(
        select(EstimateRevision).where(EstimateRevision.estimate_id == estimate.id)
    )
    assert revision is not None
    broken = zero_value_estimate_response().model_dump(mode="json")
    revision.estimate_response_payload = broken
    estimate_model = db_session.get(Estimate, estimate.id)
    assert estimate_model is not None
    estimate_model.estimate_total = 0
    db_session.add(revision)
    db_session.add(estimate_model)
    db_session.commit()

    with pytest.raises(HTTPException) as excinfo:
        await main.send_estimate_record_for_approval(
            estimate.id,
            EstimateSendForApprovalRequest(),
            db_session,
            auth,
            request_for("/api/estimates/1/send-for-approval", method="POST"),
        )
    assert excinfo.value.status_code == 422
    assert (
        "zero-value estimates cannot be sent for approval" in str(excinfo.value.detail).lower()
        or "structured estimate generation failed" in str(excinfo.value.detail).lower()
    )


@pytest.mark.anyio
async def test_forged_aggregate_totals_are_rejected_before_persistence(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_forged_total_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)
    vehicle = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_estimate_record(
            estimate_create_payload(customer_id, vehicle.id),
            db_session,
            settings,
            auth,
        )
    assert excinfo.value.status_code == 422
    assert "reconcile" in str(excinfo.value.detail).lower()
    assert db_session.scalar(select(Estimate)) is None


@pytest.mark.anyio
async def test_fabricated_zero_hour_labor_line_next_to_real_parts_is_rejected(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    """A non-empty labor_items list whose only line collapsed to zero hours/total
    must be rejected even when real parts pricing is present, so the customer
    never sees a nonsense free-labor line on an otherwise-priced estimate."""
    monkeypatch.setattr(
        OptimusResearchOrchestrator, "estimate_job", stub_partial_collapse_estimate_job
    )
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)
    vehicle = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_estimate_record(
            estimate_create_payload(customer_id, vehicle.id),
            db_session,
            settings,
            auth,
        )
    assert excinfo.value.status_code == 422
    assert "structured estimate generation failed" in str(excinfo.value.detail).lower()
    assert db_session.scalar(select(Estimate)) is None


@pytest.mark.anyio
async def test_labor_optional_parts_only_estimate_is_accepted(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    """An explicitly empty labor_items list next to real parts pricing represents
    a legitimate labor-optional job (e.g. a parts drop-ship) and must remain
    valid; only a fabricated zero-hour placeholder line is newly rejected."""
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_parts_only_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)
    vehicle = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)

    estimate = await main.create_estimate_record(
        estimate_create_payload(customer_id, vehicle.id),
        db_session,
        settings,
        auth,
    )
    assert estimate.status is EstimateStatus.DRAFT
    assert estimate.current_revision.estimate.labor_items == []
    assert estimate.current_revision.estimate.totals.estimated_total == 167.7


@pytest.mark.anyio
async def test_negative_financial_values_are_rejected_before_persistence(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        OptimusResearchOrchestrator, "estimate_job", stub_negative_value_estimate_job
    )
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id = await create_customer_for_auth(settings, db_session, auth)
    vehicle = await main.create_vehicle_record(customer_id, vehicle_payload(), db_session, auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_estimate_record(
            estimate_create_payload(customer_id, vehicle.id),
            db_session,
            settings,
            auth,
        )
    assert excinfo.value.status_code == 422
    assert (
        "negative" in str(excinfo.value.detail).lower()
        or "structured estimate generation failed" in str(excinfo.value.detail).lower()
    )
    assert db_session.scalar(select(Estimate)) is None


@pytest.mark.anyio
async def test_decline_flow_records_reason(monkeypatch, settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, _, estimate = await create_estimate_for_auth(settings, db_session, auth)

    sent = await main.send_estimate_record_for_approval(
        estimate.id,
        EstimateSendForApprovalRequest(),
        db_session,
        auth,
        request_for("/api/estimates/1/send-for-approval", method="POST"),
    )
    token = sent.approval_link.split("#token=", 1)[1]

    declined = await main.approval_decline(
        EstimateDeclineActionRequest(
            token=token,
            revision_number=1,
            declining_name="Jane Customer",
            reason="Need to wait until next month.",
        ),
        db_session,
        request_for("/api/estimate-approval/decline", method="POST"),
        settings,
    )
    assert declined.status is EstimateStatus.DECLINED

    history = await main.estimate_approval_history(estimate.id, db_session, auth)
    assert history.events[-1].decline_reason == "Need to wait until next month."


@pytest.mark.anyio
async def test_invalid_expired_and_reused_tokens_fail_safely(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, _, estimate = await create_estimate_for_auth(settings, db_session, auth)
    sent = await main.send_estimate_record_for_approval(
        estimate.id,
        EstimateSendForApprovalRequest(),
        db_session,
        auth,
        request_for("/api/estimates/1/send-for-approval", method="POST"),
    )
    token = sent.approval_link.split("#token=", 1)[1]

    with pytest.raises(HTTPException) as invalid_exc:
        await main.approval_view(
            EstimateApprovalTokenRequest(token="not-a-real-token"),
            db_session,
            request_for("/api/estimate-approval/view", method="POST"),
            settings,
        )
    assert invalid_exc.value.status_code == 404

    approval_request = db_session.scalar(select(EstimateApprovalRequest))
    assert approval_request is not None
    approval_request.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.add(approval_request)
    db_session.commit()

    with pytest.raises(HTTPException) as expired_exc:
        await main.approval_view(
            EstimateApprovalTokenRequest(token=token),
            db_session,
            request_for("/api/estimate-approval/view", method="POST"),
            settings,
        )
    assert expired_exc.value.status_code == 404


@pytest.mark.anyio
async def test_token_reuse_and_revision_mismatch(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, _, estimate = await create_estimate_for_auth(settings, db_session, auth)
    sent = await main.send_estimate_record_for_approval(
        estimate.id,
        EstimateSendForApprovalRequest(),
        db_session,
        auth,
        request_for("/api/estimates/1/send-for-approval", method="POST"),
    )
    token = sent.approval_link.split("#token=", 1)[1]

    with pytest.raises(HTTPException) as mismatch_exc:
        await main.approval_approve(
            EstimateApprovalActionRequest(
                token=token,
                revision_number=99,
                approving_name="Jane Customer",
                accepted_terms=True,
                payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
                typed_authorization="Approved",
            ),
            db_session,
            request_for("/api/estimate-approval/approve", method="POST"),
            settings,
        )
    assert mismatch_exc.value.status_code == 409

    approved = await main.approval_approve(
        EstimateApprovalActionRequest(
            token=token,
            revision_number=1,
            approving_name="Jane Customer",
            accepted_terms=True,
            payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
            typed_authorization="Approved",
        ),
        db_session,
        request_for("/api/estimate-approval/approve", method="POST"),
        settings,
    )
    assert approved.status is EstimateStatus.APPROVED

    with pytest.raises(HTTPException) as reused_exc:
        await main.approval_view(
            EstimateApprovalTokenRequest(token=token),
            db_session,
            request_for("/api/estimate-approval/view", method="POST"),
            settings,
        )
    assert reused_exc.value.status_code == 404


@pytest.mark.anyio
async def test_cross_user_access_isolated(monkeypatch, settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    create_user(db_session, username="other-owner", password="other-password-123")
    _, other_response = await login_as(
        settings,
        db_session,
        username="other-owner",
        password="other-password-123",
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    _, _, estimate = await create_estimate_for_auth(settings, db_session, owner_auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.get_estimate_record(estimate.id, db_session, other_auth)
    assert excinfo.value.status_code == 404


@pytest.mark.anyio
async def test_approval_lock_requires_new_revision(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    customer_id, vehicle, estimate = await create_estimate_for_auth(settings, db_session, auth)
    sent = await main.send_estimate_record_for_approval(
        estimate.id,
        EstimateSendForApprovalRequest(),
        db_session,
        auth,
        request_for("/api/estimates/1/send-for-approval", method="POST"),
    )
    token = sent.approval_link.split("#token=", 1)[1]
    await main.approval_approve(
        EstimateApprovalActionRequest(
            token=token,
            revision_number=1,
            approving_name="Jane Customer",
            accepted_terms=True,
            payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
            typed_authorization="Approved",
        ),
        db_session,
        request_for("/api/estimate-approval/approve", method="POST"),
        settings,
    )

    with pytest.raises(HTTPException) as locked_exc:
        await main.update_estimate_record(
            estimate.id,
            EstimateUpdate(terms_text="New terms"),
            db_session,
            auth,
        )
    assert locked_exc.value.status_code == 409

    revised = await main.create_estimate_revision_record(
        estimate.id,
        EstimateRevisionCreate(
            **estimate_create_payload(customer_id, vehicle.id).model_dump(mode="python"),
            reason="Customer changed the requested scope.",
        ),
        db_session,
        settings,
        auth,
    )
    assert revised.current_revision_number == 2
    assert revised.status is EstimateStatus.READY


@pytest.mark.anyio
async def test_payment_plan_acknowledgement_required(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, _, estimate = await create_estimate_for_auth(settings, db_session, auth)
    sent = await main.send_estimate_record_for_approval(
        estimate.id,
        EstimateSendForApprovalRequest(),
        db_session,
        auth,
        request_for("/api/estimates/1/send-for-approval", method="POST"),
    )
    token = sent.approval_link.split("#token=", 1)[1]

    with pytest.raises(HTTPException) as excinfo:
        await main.approval_approve(
            EstimateApprovalActionRequest(
                token=token,
                revision_number=1,
                approving_name="Jane Customer",
                accepted_terms=True,
                payment_option=EstimatePaymentOptionCode.TWO_MONTH_PLAN,
                payment_plan_acknowledged=False,
                typed_authorization="Approved",
            ),
            db_session,
            request_for("/api/estimate-approval/approve", method="POST"),
            settings,
        )
    assert excinfo.value.status_code == 422
    assert "acknowledgement" in str(excinfo.value.detail).lower()


@pytest.mark.anyio
async def test_approval_storage_failures_are_sanitized_and_do_not_log_tokens(
    monkeypatch, settings, db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:  # type: ignore[no-untyped-def]
    token = "sensitive-approval-token"

    def explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise SQLAlchemyError("db broke")

    monkeypatch.setattr(main, "approve_estimate", explode)
    caplog.set_level(logging.WARNING, logger="optimus")

    with pytest.raises(HTTPException) as excinfo:
        await main.approval_approve(
            EstimateApprovalActionRequest(
                token=token,
                revision_number=1,
                approving_name="Jane Customer",
                accepted_terms=True,
                payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
                typed_authorization="Approved",
            ),
            db_session,
            request_for("/api/estimate-approval/approve", method="POST"),
            settings,
        )
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Estimate storage is unavailable."
    assert token not in caplog.text


@pytest.mark.anyio
async def test_restart_persistence_for_approved_estimates(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    database_path = tmp_path / "estimate-approval.db"
    settings = Settings(
        app_env="test",
        openai_api_key="test-key",
        database_url=f"sqlite+pysqlite:///{database_path}",
        frontend_origin="http://127.0.0.1:5173",
        labor_rate=100,
        mobile_service_fee=25,
        shop_supplies_percent=5,
        parts_tax_rate=8.5,
        optimus_owner_username="owner",
        optimus_owner_password="owner-password-123",
    )
    engine = build_engine(settings.database_url)
    Base.metadata.create_all(bind=engine)
    session_factory = build_session_factory(settings.database_url)
    first_session = session_factory()
    try:
        bootstrap_owner_account(settings=settings, db=first_session)
        _, response = await login_as(settings, first_session)
        auth = auth_context(settings, first_session, raw_cookie_from_response(response))
        _, _, estimate = await create_estimate_for_auth(settings, first_session, auth)
        sent = await main.send_estimate_record_for_approval(
            estimate.id,
            EstimateSendForApprovalRequest(),
            first_session,
            auth,
            request_for("/api/estimates/1/send-for-approval", method="POST"),
        )
        token = sent.approval_link.split("#token=", 1)[1]
        await main.approval_approve(
            EstimateApprovalActionRequest(
                token=token,
                revision_number=1,
                approving_name="Jane Customer",
                accepted_terms=True,
                payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
                typed_authorization="Approved",
            ),
            first_session,
            request_for("/api/estimate-approval/approve", method="POST"),
            settings,
        )
    finally:
        first_session.close()

    second_session = session_factory()
    try:
        _, response = await login_as(settings, second_session)
        auth = auth_context(settings, second_session, raw_cookie_from_response(response))
        persisted = await main.get_estimate_record(1, second_session, auth)
        assert persisted.status is EstimateStatus.APPROVED
        events = second_session.scalars(select(EstimateApprovalEvent)).all()
        assert [event.event_type for event in events] == ["sent", "approved"]
    finally:
        second_session.close()
