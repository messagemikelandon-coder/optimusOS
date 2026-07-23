from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.main as main
from app.models import (
    CustomerCreate,
    DiagnosticConfidence,
    DiagnosticFindingCreate,
    DiagnosticFindingUpdate,
    DiagnosticSeverity,
    EstimatePaymentOptionCode,
    InspectionCreate,
    InspectionItem,
    InspectionUpdate,
    TechnicianCreate,
    TechnicianProvisionLoginRequest,
    VehicleCreate,
    VehicleRead,
    WorkOrderAssignTechnicianRequest,
)
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_work_orders_api import create_approved_estimate_for_auth

pytestmark = pytest.mark.anyio


async def _create_vehicle(settings, db_session: Session, auth) -> VehicleRead:
    customer = await main.create_customer_record(
        CustomerCreate(first_name="Sample", last_name="Customer"), db_session, auth
    )
    return await main.create_vehicle_record(
        customer.id,
        VehicleCreate(year=2018, make="Honda", model="Civic"),
        db_session,
        auth,
    )


async def _create_technician_with_assigned_work_order(
    monkeypatch, settings, db_session, owner_auth
):
    """Real end-to-end setup (not a direct DB row insert) matching the exact
    pattern already established in tests/test_technicians_api.py: an approved
    estimate -> a real work order -> a real technician account with real
    login -> the owner assigning that work order to that technician. Returns
    (technician_auth, work_order, vehicle) so a test can create a finding
    tied to work_order.id/vehicle.id as that technician."""
    vehicle, estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        owner_auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
    )
    work_order = await main.create_work_order_record(estimate.id, db_session, owner_auth)
    technician = await main.create_technician_record(
        TechnicianCreate(first_name="Jordan", last_name="Reyes", employment_status="Full-time"),
        db_session,
        owner_auth,
    )
    await main.provision_technician_login_record(
        technician.id,
        TechnicianProvisionLoginRequest(username="jordan.reyes", password="tech-login-pass-123"),
        db_session,
        owner_auth,
    )
    _, login_response = await login_as(
        settings, db_session, username="jordan.reyes", password="tech-login-pass-123"
    )
    technician_auth = auth_context(settings, db_session, raw_cookie_from_response(login_response))
    await main.assign_work_order_technician_record(
        work_order.id,
        WorkOrderAssignTechnicianRequest(technician_id=technician.id),
        db_session,
        owner_auth,
    )
    return technician_auth, work_order, vehicle


async def test_diagnostic_findings_require_authenticated_session(
    settings, db_session: Session
) -> None:
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/diagnostic-findings"), db_session, settings)
    assert excinfo.value.status_code == 401


async def test_create_and_update_diagnostic_finding(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(
            vehicle_id=vehicle.id,
            codes="P0301",
            symptoms="Rough idle at startup.",
        ),
        db_session,
        auth,
    )
    assert created.vehicle_display_name == vehicle.display_name
    assert created.codes == "P0301"

    updated = await main.update_diagnostic_finding_record(
        created.id,
        DiagnosticFindingUpdate(conclusion="Replaced ignition coil #3."),
        db_session,
        auth,
    )
    assert updated.conclusion == "Replaced ignition coil #3."
    assert updated.symptoms == "Rough idle at startup."


async def test_diagnostic_evidence_fields_round_trip(settings, db_session: Session) -> None:
    # The Diagnostic Evidence Engine's structured fields (complaint, severity,
    # confidence, recommended next test) persist and read back.
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(
            vehicle_id=vehicle.id,
            complaint="Grinding noise when braking.",
            symptoms="Metal-on-metal at front axle under braking.",
            tests_performed="Measured front pad thickness at 1mm; rotor scored.",
            severity=DiagnosticSeverity.UNSAFE,
            confidence=DiagnosticConfidence.CONFIRMED,
            recommended_next_test="Confirm caliper slide-pin freedom after pad replacement.",
            conclusion="Front brake pads worn out; rotors scored.",
        ),
        db_session,
        auth,
    )
    assert created.complaint == "Grinding noise when braking."
    assert created.severity is DiagnosticSeverity.UNSAFE
    assert created.confidence is DiagnosticConfidence.CONFIRMED
    assert (
        created.recommended_next_test == "Confirm caliper slide-pin freedom after pad replacement."
    )
    # A conclusion backed by a confidence level is not flagged unverified.
    assert created.diagnosis_unverified is False

    fetched = await main.get_diagnostic_finding_record(created.id, db_session, auth)
    assert fetched.severity is DiagnosticSeverity.UNSAFE
    assert fetched.confidence is DiagnosticConfidence.CONFIRMED
    assert fetched.diagnosis_unverified is False


async def test_conclusion_without_confidence_is_flagged_unverified(
    settings, db_session: Session
) -> None:
    # "No unsupported diagnosis stated as fact": a conclusion recorded without a
    # confidence level is surfaced as an unverified working theory, not a fact.
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(
            vehicle_id=vehicle.id,
            symptoms="Intermittent misfire.",
            conclusion="Likely a failing coil pack.",
        ),
        db_session,
        auth,
    )
    assert created.conclusion == "Likely a failing coil pack."
    assert created.confidence is None
    assert created.diagnosis_unverified is True

    # Adding a confidence level later clears the unverified flag.
    verified = await main.update_diagnostic_finding_record(
        created.id,
        DiagnosticFindingUpdate(confidence=DiagnosticConfidence.CONFIRMED),
        db_session,
        auth,
    )
    assert verified.diagnosis_unverified is False


async def test_no_conclusion_is_not_flagged_unverified(settings, db_session: Session) -> None:
    # A finding still gathering evidence (no conclusion) asserts nothing, so it is
    # never flagged as an unverified diagnosis.
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(
            vehicle_id=vehicle.id,
            symptoms="Rough idle.",
            severity=DiagnosticSeverity.ADVISORY,
        ),
        db_session,
        auth,
    )
    assert created.conclusion is None
    assert created.diagnosis_unverified is False


async def test_diagnostic_finding_rejects_invalid_enum_values(
    settings, db_session: Session
) -> None:
    # Enum-typed evidence fields reject out-of-range values at the model boundary.
    # Built via model_validate so the invalid literals are rejected at runtime
    # (the typed constructor would reject them at type-check time instead).
    with pytest.raises(ValueError):
        DiagnosticFindingCreate.model_validate(
            {"vehicle_id": 1, "symptoms": "x", "severity": "catastrophic"}
        )
    with pytest.raises(ValueError):
        DiagnosticFindingCreate.model_validate(
            {"vehicle_id": 1, "symptoms": "x", "confidence": "certain"}
        )


async def test_diagnostic_finding_rejects_unknown_vehicle(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    with pytest.raises(HTTPException) as excinfo:
        await main.create_diagnostic_finding_record(
            DiagnosticFindingCreate(vehicle_id=999999, symptoms="Test"), db_session, auth
        )
    assert excinfo.value.status_code == 422


async def test_diagnostic_finding_cross_owner_isolation(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    vehicle = await _create_vehicle(settings, db_session, owner_auth)

    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Test"), db_session, owner_auth
    )

    # A second owner cannot even reference the first owner's vehicle.
    with pytest.raises(HTTPException) as create_exc:
        await main.create_diagnostic_finding_record(
            DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Test"),
            db_session,
            other_auth,
        )
    assert create_exc.value.status_code == 422

    with pytest.raises(HTTPException) as get_exc:
        await main.get_diagnostic_finding_record(created.id, db_session, other_auth)
    assert get_exc.value.status_code == 404


async def test_archive_diagnostic_finding(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)
    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Test"), db_session, auth
    )
    assert created.is_archived is False

    archived = await main.archive_diagnostic_finding_record(created.id, db_session, auth)
    assert archived.finding.is_archived is True
    assert archived.finding.archived_at is not None

    # Archiving is not deletion: the record is still retrievable directly and
    # its history survives -- only the default (active) list excludes it.
    fetched = await main.get_diagnostic_finding_record(created.id, db_session, auth)
    assert fetched.is_archived is True

    active_list = await main.list_diagnostic_finding_records(
        db_session, settings, auth, page=1, page_size=20, vehicle_id=None, work_order_id=None
    )
    assert created.id not in [item.id for item in active_list.items]

    archived_list = await main.list_diagnostic_finding_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        vehicle_id=None,
        work_order_id=None,
        archived=True,
    )
    assert created.id in [item.id for item in archived_list.items]

    # Archiving is idempotent -- unlike a plain boolean-only archive flag, this
    # module also has archived_at/archived_by and an append-only event log, so
    # idempotency must be enforced explicitly rather than assumed safe by
    # re-running the same unconditional write.
    reachived = await main.archive_diagnostic_finding_record(created.id, db_session, auth)
    assert reachived.finding.is_archived is True
    assert reachived.finding.archived_at == archived.finding.archived_at

    history_after_double_archive = await main.list_diagnostic_finding_event_records(
        created.id, db_session, auth
    )
    assert [event.event_type for event in history_after_double_archive.events] == [
        "created",
        "archived",
    ]


async def test_diagnostic_finding_archive_is_owner_scoped(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    vehicle = await _create_vehicle(settings, db_session, owner_auth)
    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Test"), db_session, owner_auth
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.archive_diagnostic_finding_record(created.id, db_session, other_auth)
    assert excinfo.value.status_code == 404


async def test_diagnostic_finding_events_record_created_updated_archived(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)
    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Test"), db_session, auth
    )
    await main.update_diagnostic_finding_record(
        created.id, DiagnosticFindingUpdate(conclusion="Fixed."), db_session, auth
    )
    await main.archive_diagnostic_finding_record(created.id, db_session, auth)

    history = await main.list_diagnostic_finding_event_records(created.id, db_session, auth)
    assert history.finding_id == created.id
    assert [event.event_type for event in history.events] == ["created", "updated", "archived"]
    for event in history.events:
        assert event.actor_type == "owner"
        assert event.actor_name == "Owner"

    with pytest.raises(HTTPException) as excinfo:
        await main.list_diagnostic_finding_event_records(999999, db_session, auth)
    assert excinfo.value.status_code == 404


async def test_diagnostic_finding_empty_update_does_not_record_an_event(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)
    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Test"), db_session, auth
    )

    # A PATCH with no fields set is a no-op and should not pollute the
    # append-only audit log with a spurious "updated" entry.
    await main.update_diagnostic_finding_record(
        created.id, DiagnosticFindingUpdate(), db_session, auth
    )

    history = await main.list_diagnostic_finding_event_records(created.id, db_session, auth)
    assert [event.event_type for event in history.events] == ["created"]


async def test_create_and_update_inspection_with_items(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)

    created = await main.create_inspection_record(
        InspectionCreate(
            vehicle_id=vehicle.id,
            inspection_type="Multi-point",
            items=[
                InspectionItem(label="Brake pads", status="ok"),
                InspectionItem(label="Tire tread", status="attention", note="4/32 remaining"),
            ],
        ),
        db_session,
        auth,
    )
    assert len(created.items) == 2
    assert created.has_attention_items is True
    assert created.has_failed_items is False

    updated = await main.update_inspection_record(
        created.id,
        InspectionUpdate(
            items=[
                InspectionItem(label="Brake pads", status="fail", note="Below minimum"),
            ]
        ),
        db_session,
        auth,
    )
    assert len(updated.items) == 1
    assert updated.has_failed_items is True
    assert updated.has_attention_items is False


async def test_inspection_cross_owner_isolation(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    vehicle = await _create_vehicle(settings, db_session, owner_auth)

    created = await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id), db_session, owner_auth
    )

    other_list = await main.list_inspection_records(
        db_session,
        settings,
        other_auth,
        page=1,
        page_size=20,
        vehicle_id=None,
        work_order_id=None,
    )
    assert other_list.items == []

    with pytest.raises(HTTPException) as excinfo:
        await main.get_inspection_record(created.id, db_session, other_auth)
    assert excinfo.value.status_code == 404


async def test_archive_inspection(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)
    created = await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id), db_session, auth
    )
    assert created.is_archived is False

    archived = await main.archive_inspection_record(created.id, db_session, auth)
    assert archived.inspection.is_archived is True
    assert archived.inspection.archived_at is not None

    fetched = await main.get_inspection_record(created.id, db_session, auth)
    assert fetched.is_archived is True

    active_list = await main.list_inspection_records(
        db_session, settings, auth, page=1, page_size=20, vehicle_id=None, work_order_id=None
    )
    assert created.id not in [item.id for item in active_list.items]

    archived_list = await main.list_inspection_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        vehicle_id=None,
        work_order_id=None,
        archived=True,
    )
    assert created.id in [item.id for item in archived_list.items]

    reachived = await main.archive_inspection_record(created.id, db_session, auth)
    assert reachived.inspection.is_archived is True
    assert reachived.inspection.archived_at == archived.inspection.archived_at

    history_after_double_archive = await main.list_inspection_event_records(
        created.id, db_session, auth
    )
    assert [event.event_type for event in history_after_double_archive.events] == [
        "created",
        "archived",
    ]


async def test_inspection_archive_is_owner_scoped(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))
    vehicle = await _create_vehicle(settings, db_session, owner_auth)
    created = await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id), db_session, owner_auth
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.archive_inspection_record(created.id, db_session, other_auth)
    assert excinfo.value.status_code == 404


async def test_inspection_events_record_created_updated_archived(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)
    created = await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id), db_session, auth
    )
    await main.update_inspection_record(
        created.id, InspectionUpdate(overall_notes="Looks good."), db_session, auth
    )
    await main.archive_inspection_record(created.id, db_session, auth)

    history = await main.list_inspection_event_records(created.id, db_session, auth)
    assert history.inspection_id == created.id
    assert [event.event_type for event in history.events] == ["created", "updated", "archived"]
    for event in history.events:
        assert event.actor_type == "owner"
        assert event.actor_name == "Owner"

    with pytest.raises(HTTPException) as excinfo:
        await main.list_inspection_event_records(999999, db_session, auth)
    assert excinfo.value.status_code == 404


async def test_inspection_empty_update_does_not_record_an_event(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vehicle = await _create_vehicle(settings, db_session, auth)
    created = await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id), db_session, auth
    )

    await main.update_inspection_record(created.id, InspectionUpdate(), db_session, auth)

    history = await main.list_inspection_event_records(created.id, db_session, auth)
    assert [event.event_type for event in history.events] == ["created"]


async def test_diagnostic_finding_rejects_cross_owner_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    """Regression test for an independent-review finding: vehicle_id and
    technician_id were validated against the caller's own owner scope, but
    work_order_id was written straight through with no ownership check --
    a real cross-tenant write-path isolation gap on a field the DB-level FK
    alone can't catch (it only proves the row exists, not who owns it)."""
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    _, owner_estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        owner_auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
    )
    owner_work_order = await main.create_work_order_record(
        owner_estimate.id, db_session, owner_auth
    )
    other_vehicle = await _create_vehicle(settings, db_session, other_auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_diagnostic_finding_record(
            DiagnosticFindingCreate(
                vehicle_id=other_vehicle.id,
                work_order_id=owner_work_order.id,
                symptoms="Test",
            ),
            db_session,
            other_auth,
        )
    assert excinfo.value.status_code == 422


async def test_inspection_rejects_cross_owner_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    _, owner_estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        owner_auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
    )
    owner_work_order = await main.create_work_order_record(
        owner_estimate.id, db_session, owner_auth
    )
    other_vehicle = await _create_vehicle(settings, db_session, other_auth)

    with pytest.raises(HTTPException) as excinfo:
        await main.create_inspection_record(
            InspectionCreate(vehicle_id=other_vehicle.id, work_order_id=owner_work_order.id),
            db_session,
            other_auth,
        )
    assert excinfo.value.status_code == 422


async def test_technician_can_create_view_and_update_finding_on_own_assigned_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    technician_auth, work_order, vehicle = await _create_technician_with_assigned_work_order(
        monkeypatch, settings, db_session, owner_auth
    )

    created = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(
            vehicle_id=vehicle.id, work_order_id=work_order.id, symptoms="Rough idle"
        ),
        db_session,
        technician_auth,
    )
    assert created.work_order_id == work_order.id

    # The technician can read and update their own finding.
    fetched = await main.get_diagnostic_finding_record(created.id, db_session, technician_auth)
    assert fetched.id == created.id
    updated = await main.update_diagnostic_finding_record(
        created.id,
        DiagnosticFindingUpdate(conclusion="Vacuum leak found."),
        db_session,
        technician_auth,
    )
    assert updated.conclusion == "Vacuum leak found."

    technician_list = await main.list_diagnostic_finding_records(
        db_session,
        settings,
        technician_auth,
        page=1,
        page_size=20,
        vehicle_id=None,
        work_order_id=None,
    )
    assert created.id in [item.id for item in technician_list.items]

    # The owner (whose shop this is) can see it too.
    owner_fetched = await main.get_diagnostic_finding_record(created.id, db_session, owner_auth)
    assert owner_fetched.id == created.id


async def test_technician_diagnostic_finding_write_path_is_scoped_to_own_assigned_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    technician_auth, work_order, vehicle = await _create_technician_with_assigned_work_order(
        monkeypatch, settings, db_session, owner_auth
    )

    # A finding with no work order at all is invisible to a technician, even
    # though it belongs to the same shop -- "own assigned work orders" only.
    unlinked = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="No codes yet"),
        db_session,
        owner_auth,
    )
    with pytest.raises(HTTPException) as unlinked_exc:
        await main.get_diagnostic_finding_record(unlinked.id, db_session, technician_auth)
    assert unlinked_exc.value.status_code == 404

    # A technician cannot create a finding without linking a work order.
    with pytest.raises(HTTPException) as missing_wo_exc:
        await main.create_diagnostic_finding_record(
            DiagnosticFindingCreate(vehicle_id=vehicle.id, symptoms="Test"),
            db_session,
            technician_auth,
        )
    assert missing_wo_exc.value.status_code == 422

    # A technician cannot link a finding to a work order that exists (same
    # shop) but is not assigned to them.
    _, other_estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        owner_auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
        vin="1FTFW1ET1EFA00002",
    )
    unassigned_work_order = await main.create_work_order_record(
        other_estimate.id, db_session, owner_auth
    )
    with pytest.raises(HTTPException) as unassigned_exc:
        await main.create_diagnostic_finding_record(
            DiagnosticFindingCreate(
                vehicle_id=vehicle.id, work_order_id=unassigned_work_order.id, symptoms="Test"
            ),
            db_session,
            technician_auth,
        )
    assert unassigned_exc.value.status_code == 422

    # A technician cannot link a finding to their own assigned work order
    # while citing an unrelated vehicle -- do not rely on the work-order FK
    # alone.
    other_vehicle = await _create_vehicle(settings, db_session, owner_auth)
    with pytest.raises(HTTPException) as mismatch_exc:
        await main.create_diagnostic_finding_record(
            DiagnosticFindingCreate(
                vehicle_id=other_vehicle.id, work_order_id=work_order.id, symptoms="Test"
            ),
            db_session,
            technician_auth,
        )
    assert mismatch_exc.value.status_code == 422


async def test_technician_can_create_view_and_update_inspection_on_own_assigned_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    technician_auth, work_order, vehicle = await _create_technician_with_assigned_work_order(
        monkeypatch, settings, db_session, owner_auth
    )

    created = await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id, work_order_id=work_order.id),
        db_session,
        technician_auth,
    )
    assert created.work_order_id == work_order.id

    fetched = await main.get_inspection_record(created.id, db_session, technician_auth)
    assert fetched.id == created.id
    updated = await main.update_inspection_record(
        created.id,
        InspectionUpdate(overall_notes="All clear."),
        db_session,
        technician_auth,
    )
    assert updated.overall_notes == "All clear."

    technician_list = await main.list_inspection_records(
        db_session,
        settings,
        technician_auth,
        page=1,
        page_size=20,
        vehicle_id=None,
        work_order_id=None,
    )
    assert created.id in [item.id for item in technician_list.items]

    owner_fetched = await main.get_inspection_record(created.id, db_session, owner_auth)
    assert owner_fetched.id == created.id


async def test_technician_inspection_write_path_is_scoped_to_own_assigned_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    _, owner_response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    technician_auth, work_order, vehicle = await _create_technician_with_assigned_work_order(
        monkeypatch, settings, db_session, owner_auth
    )

    unlinked = await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id), db_session, owner_auth
    )
    with pytest.raises(HTTPException) as unlinked_exc:
        await main.get_inspection_record(unlinked.id, db_session, technician_auth)
    assert unlinked_exc.value.status_code == 404

    with pytest.raises(HTTPException) as missing_wo_exc:
        await main.create_inspection_record(
            InspectionCreate(vehicle_id=vehicle.id), db_session, technician_auth
        )
    assert missing_wo_exc.value.status_code == 422

    _, other_estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        owner_auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
        vin="1FTFW1ET1EFA00003",
    )
    unassigned_work_order = await main.create_work_order_record(
        other_estimate.id, db_session, owner_auth
    )
    with pytest.raises(HTTPException) as unassigned_exc:
        await main.create_inspection_record(
            InspectionCreate(vehicle_id=vehicle.id, work_order_id=unassigned_work_order.id),
            db_session,
            technician_auth,
        )
    assert unassigned_exc.value.status_code == 422

    other_vehicle = await _create_vehicle(settings, db_session, owner_auth)
    with pytest.raises(HTTPException) as mismatch_exc:
        await main.create_inspection_record(
            InspectionCreate(vehicle_id=other_vehicle.id, work_order_id=work_order.id),
            db_session,
            technician_auth,
        )
    assert mismatch_exc.value.status_code == 422
