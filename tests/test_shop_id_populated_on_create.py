from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.db_models import (
    Appointment,
    Bay,
    DiagnosticFinding,
    DiagnosticFindingEvent,
    Estimate,
    EstimateApprovalEvent,
    EstimateApprovalRequest,
    EstimateRevision,
    Inspection,
    InspectionEvent,
    IntakeRequest,
    Invoice,
    InvoicePayment,
    Notification,
    Part,
    PartAllocation,
    PartAllocationEvent,
    PaymentSchedule,
    PurchaseOrder,
    PurchaseOrderReceipt,
    ScheduleBlock,
    Shop,
    ShopMembership,
    Technician,
    TechnicianTimeEntry,
    Vehicle,
    Vendor,
    WorkingHours,
    WorkOrder,
    WorkOrderNote,
    WorkOrderStatusEvent,
)
from app.models import (
    AppointmentCreate,
    BayCreate,
    CustomerCreate,
    DiagnosticFindingCreate,
    EstimateApprovalActionRequest,
    EstimateApprovalTokenRequest,
    EstimatePaymentOptionCode,
    EstimateSendForApprovalRequest,
    InspectionCreate,
    IntakeRequestCreate,
    InvoiceIssueRequest,
    InvoicePaymentCreate,
    PartAllocationAllocateRequest,
    PartAllocationCreate,
    PartCreate,
    PaymentAppliesTo,
    PurchaseOrderCreate,
    PurchaseOrderLineItemCreate,
    PurchaseOrderReceiveRequest,
    ScheduleBlockCreate,
    TechnicianCreate,
    TechnicianProvisionLoginRequest,
    VehicleCreate,
    VendorCreate,
    WorkingHoursCreate,
    WorkOrderNoteCreate,
    WorkOrderNoteVisibility,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
)
from app.orchestrator import OptimusResearchOrchestrator
from app.scheduling_store import SHOP_TIMEZONE
from tests.test_api import request_for
from tests.test_context_api import auth_context, login_as, raw_cookie_from_response
from tests.test_estimate_approval_api import create_estimate_for_auth, stub_estimate_job

pytestmark = pytest.mark.anyio


async def test_shop_id_is_set_on_creation_across_every_business_table(
    monkeypatch, settings, db_session: Session
) -> None:
    """Closes a real coverage gap independent review found in PR #55: the
    only test proving `shop_id` gets populated on create exercised
    `Customer` alone (via a real-HTTP e2e test). This walks a single
    authenticated owner through creating at least one row in every one of
    the 30 business tables this slice touches, asserting each row's
    `shop_id` matches the owner's real shop -- not just that the schema
    supports it, but that every store module's actual create path sets it
    correctly. Uses the fast sqlite suite (not e2e/real Postgres) since
    resolving `shop_id` doesn't depend on any Postgres-specific behavior,
    matching how the rest of this test suite already exercises store
    modules directly through the real route functions in `app.main`.
    """
    monkeypatch.setattr(OptimusResearchOrchestrator, "estimate_job", stub_estimate_job)
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    shop = db_session.scalar(select(Shop))
    assert shop is not None
    membership = db_session.scalar(select(ShopMembership))
    assert membership is not None
    assert membership.shop_id == shop.id

    def assert_shop(model_cls: type, row_id: int) -> None:
        row = db_session.get(model_cls, row_id)
        assert row is not None, f"{model_cls.__name__} id={row_id} not found"
        assert row.shop_id == shop.id, f"{model_cls.__name__} id={row_id} has wrong shop_id"

    # Customer, Vehicle, Estimate, EstimateRevision
    _customer_id, vehicle, estimate = await create_estimate_for_auth(settings, db_session, auth)
    assert_shop(Vehicle, vehicle.id)
    assert_shop(Estimate, estimate.id)
    assert_shop(EstimateRevision, estimate.current_revision.id)

    # EstimateApprovalRequest, EstimateApprovalEvent, Notification (sent)
    sent = await main.send_estimate_record_for_approval(
        estimate.id,
        EstimateSendForApprovalRequest(),
        db_session,
        auth,
        request_for("/api/estimates/1/send-for-approval", method="POST"),
    )
    approval_request_id = db_session.scalar(
        select(EstimateApprovalRequest.id).where(EstimateApprovalRequest.estimate_id == estimate.id)
    )
    assert approval_request_id is not None
    assert_shop(EstimateApprovalRequest, approval_request_id)
    event_id = db_session.scalar(
        select(EstimateApprovalEvent.id).where(EstimateApprovalEvent.estimate_id == estimate.id)
    )
    assert event_id is not None
    assert_shop(EstimateApprovalEvent, event_id)

    token = sent.approval_link.split("#token=", 1)[1]
    approval_view = await main.approval_view(
        EstimateApprovalTokenRequest(token=token),
        db_session,
        request_for("/api/estimate-approval/view", method="POST"),
        settings,
    )
    await main.approval_approve(
        EstimateApprovalActionRequest(
            token=token,
            revision_number=approval_view.revision.revision_number,
            approving_name="Jane Customer",
            accepted_terms=True,
            payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
            payment_plan_acknowledged=False,
            typed_authorization="Jane Customer approves the estimate.",
        ),
        db_session,
        request_for("/api/estimate-approval/approve", method="POST"),
        settings,
    )
    notification_id = db_session.scalar(select(Notification.id))
    assert notification_id is not None
    assert_shop(Notification, notification_id)

    # WorkOrder, WorkOrderStatusEvent, WorkOrderNote, Invoice, PaymentSchedule
    work_order = await main.create_work_order_record(estimate.id, db_session, auth)
    assert_shop(WorkOrder, work_order.id)
    status_event_id = db_session.scalar(
        select(WorkOrderStatusEvent.id).where(WorkOrderStatusEvent.work_order_id == work_order.id)
    )
    assert status_event_id is not None
    assert_shop(WorkOrderStatusEvent, status_event_id)

    await main.add_work_order_note_record(
        work_order.id,
        WorkOrderNoteCreate(visibility=WorkOrderNoteVisibility.INTERNAL, note="Test note"),
        db_session,
        auth,
    )
    note_id = db_session.scalar(
        select(WorkOrderNote.id).where(WorkOrderNote.work_order_id == work_order.id)
    )
    assert note_id is not None
    assert_shop(WorkOrderNote, note_id)

    for status in (
        WorkOrderStatus.SCHEDULED,
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.COMPLETED,
    ):
        work_order = await main.update_work_order_status_record(
            work_order.id,
            WorkOrderStatusUpdate(status=status, reason="Progressing"),
            db_session,
            auth,
        )
    assert work_order.invoice_id is not None
    assert_shop(Invoice, work_order.invoice_id)

    # InvoicePayment, PaymentSchedule (schedule is generated at issue time)
    issued = await main.issue_invoice_record(
        work_order.invoice_id, InvoiceIssueRequest(due_in_days=15), db_session, settings, auth
    )
    schedule_id = db_session.scalar(
        select(PaymentSchedule.id).where(PaymentSchedule.invoice_id == work_order.invoice_id)
    )
    assert schedule_id is not None
    assert_shop(PaymentSchedule, schedule_id)
    payment = await main.record_invoice_payment(
        issued.id,
        InvoicePaymentCreate(
            amount=issued.invoice_total, method_label="cash", applies_to=PaymentAppliesTo.FULL
        ),
        db_session,
        auth,
    )
    assert_shop(InvoicePayment, payment.id)

    # Technician, TechnicianTimeEntry
    technician = await main.create_technician_record(
        TechnicianCreate(first_name="Alex", last_name="Chen", employment_status="Full-time"),
        db_session,
        auth,
    )
    assert_shop(Technician, technician.id)
    await main.provision_technician_login_record(
        technician.id,
        TechnicianProvisionLoginRequest(username="alex.chen", password="tech-login-pass-456"),
        db_session,
        auth,
    )
    _, tech_login_response = await login_as(
        settings, db_session, username="alex.chen", password="tech-login-pass-456"
    )
    tech_auth = auth_context(settings, db_session, raw_cookie_from_response(tech_login_response))
    await main.clock_in_record(db_session, tech_auth)
    time_entry_id = db_session.scalar(
        select(TechnicianTimeEntry.id).where(TechnicianTimeEntry.technician_id == technician.id)
    )
    assert time_entry_id is not None
    assert_shop(TechnicianTimeEntry, time_entry_id)

    # Vendor, Part
    vendor = await main.create_vendor_record(
        VendorCreate(name="AutoZone Commercial", contact_name="Pat Rivera"), db_session, auth
    )
    assert_shop(Vendor, vendor.id)
    part = await main.create_part_record(
        PartCreate(
            part_number="BP-4471",
            description="Front brake pad set",
            quantity_on_hand=10,
            unit_cost=22.50,
            unit_price=48.00,
        ),
        db_session,
        auth,
    )
    assert_shop(Part, part.id)

    # PurchaseOrder, PurchaseOrderReceipt
    purchase_order = await main.create_purchase_order_record(
        PurchaseOrderCreate(
            vendor_id=vendor.id,
            line_items=[
                PurchaseOrderLineItemCreate(part_id=part.id, quantity_ordered=5, unit_cost=5.25)
            ],
        ),
        db_session,
        auth,
    )
    assert_shop(PurchaseOrder, purchase_order.id)
    await main.submit_purchase_order_record(purchase_order.id, db_session, auth)
    await main.receive_purchase_order_record(
        purchase_order.id,
        PurchaseOrderReceiveRequest(line_item_id=purchase_order.line_items[0].id, quantity=2),
        db_session,
        auth,
    )
    receipt_id = db_session.scalar(
        select(PurchaseOrderReceipt.id).where(
            PurchaseOrderReceipt.purchase_order_id == purchase_order.id
        )
    )
    assert receipt_id is not None
    assert_shop(PurchaseOrderReceipt, receipt_id)

    # PartAllocation, PartAllocationEvent
    allocation = await main.create_part_allocation_record(
        work_order.id,
        PartAllocationCreate(part_id=part.id, quantity_required=1),
        db_session,
        auth,
    )
    assert_shop(PartAllocation, allocation.id)
    await main.allocate_part_record(
        allocation.id,
        PartAllocationAllocateRequest(quantity=1),
        db_session,
        auth,
    )
    allocation_event_id = db_session.scalar(
        select(PartAllocationEvent.id).where(PartAllocationEvent.allocation_id == allocation.id)
    )
    assert allocation_event_id is not None
    assert_shop(PartAllocationEvent, allocation_event_id)

    # IntakeRequest
    intake = await main.create_intake_request_record(
        IntakeRequestCreate(
            customer_name="Jordan Reyes",
            phone="(555) 987-6543",
            vehicle_description="2018 Honda Civic",
            complaint="Grinding noise when braking.",
        ),
        db_session,
        auth,
    )
    assert_shop(IntakeRequest, intake.id)

    # DiagnosticFinding, DiagnosticFindingEvent (fired automatically on create)
    finding = await main.create_diagnostic_finding_record(
        DiagnosticFindingCreate(vehicle_id=vehicle.id, codes="P0301", symptoms="Rough idle."),
        db_session,
        auth,
    )
    assert_shop(DiagnosticFinding, finding.id)
    finding_event_id = db_session.scalar(
        select(DiagnosticFindingEvent.id).where(DiagnosticFindingEvent.finding_id == finding.id)
    )
    assert finding_event_id is not None
    assert_shop(DiagnosticFindingEvent, finding_event_id)

    # Inspection, InspectionEvent (fired automatically on create)
    inspection = await main.create_inspection_record(
        InspectionCreate(vehicle_id=vehicle.id, inspection_type="Multi-point"),
        db_session,
        auth,
    )
    assert_shop(Inspection, inspection.id)
    inspection_event_id = db_session.scalar(
        select(InspectionEvent.id).where(InspectionEvent.inspection_id == inspection.id)
    )
    assert inspection_event_id is not None
    assert_shop(InspectionEvent, inspection_event_id)

    # Bay, WorkingHours, ScheduleBlock, Appointment
    bay = await main.create_bay_record(BayCreate(name="Bay 1"), db_session, auth)
    assert_shop(Bay, bay.id)

    # Pick a real future Monday 10am (shop timezone) so the appointment
    # below falls inside these same working hours, rather than a
    # hardcoded day_of_week that may not match "today + N days".
    now_shop_tz = datetime.now(SHOP_TIMEZONE)
    days_until_monday = (7 - now_shop_tz.weekday()) % 7 or 7
    next_monday = (now_shop_tz + timedelta(days=days_until_monday)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    working_hours = await main.create_working_hours_record(
        WorkingHoursCreate(
            technician_id=technician.id, day_of_week=0, start_minute=480, end_minute=1020
        ),
        db_session,
        auth,
    )
    assert_shop(WorkingHours, working_hours.id)

    schedule_block_start = next_monday + timedelta(days=2)  # Wednesday, outside the appointment
    schedule_block = await main.create_schedule_block_record(
        ScheduleBlockCreate(
            technician_id=technician.id,
            start_time=schedule_block_start,
            end_time=schedule_block_start + timedelta(hours=1),
            reason="Training",
        ),
        db_session,
        auth,
    )
    assert_shop(ScheduleBlock, schedule_block.id)

    second_customer = await main.create_customer_record(
        CustomerCreate(first_name="Second", last_name="Customer"), db_session, auth
    )
    second_vehicle = await main.create_vehicle_record(
        second_customer.id,
        VehicleCreate(year=2021, make="Ford", model="Focus"),
        db_session,
        auth,
    )
    appointment = await main.create_appointment_record(
        AppointmentCreate(
            customer_id=second_customer.id,
            vehicle_id=second_vehicle.id,
            technician_id=technician.id,
            service_type="Oil change",
            start_time=next_monday,
            end_time=next_monday + timedelta(hours=1),
        ),
        db_session,
        auth,
    )
    assert_shop(Appointment, appointment.id)
