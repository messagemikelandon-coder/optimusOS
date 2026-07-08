from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

import app.main as main
from app.invoice_store import render_invoice_html, render_invoice_pdf
from app.models import EstimateApprovalTokenRequest, EstimateSendForApprovalRequest
from tests.test_api import request_for
from tests.test_context_api import auth_context, login_as, raw_cookie_from_response
from tests.test_estimate_approval_api import (
    create_estimate_for_auth,
    stub_sensitive_research_estimate_job,
)
from tests.test_invoices_api import extract_pdf_text
from tests.test_payments_api import create_completed_work_order_with_invoice, issue

pytestmark = pytest.mark.anyio

FORBIDDEN_MARKERS = (
    "INTERNAL-LABOR-BASIS-MARKER-7788",
    "INTERNAL-SPECIAL-TOOL-MARKER-7788",
    "INTERNAL-RISK-FLAG-MARKER-7788",
    "UNSELECTED-COMPETITOR-RETAILER-7788",
)


async def test_invoice_html_and_pdf_exclude_forbidden_internal_fields(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    """Phase 4 deliverable 5 (document exposure scan). This assertion largely
    overlaps `test_invoice_html_and_pdf_exclude_internal_fields` in
    `tests/test_invoices_api.py` -- kept here anyway because the roadmap
    names a consolidated exposure scan across every customer-facing surface
    as its own Phase 4 deliverable, not because this is new coverage.
    Invoice HTML/PDF are built from labor_items/selected_parts/fee_items,
    never from `research`, so this guards against a future regression that
    accidentally wires research fields into the customer-facing template."""
    monkeypatch.setattr(
        main.OptimusResearchOrchestrator, "estimate_job", stub_sensitive_research_estimate_job
    )
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch,
        settings,
        db_session,
        auth,
        estimate_job_stub=stub_sensitive_research_estimate_job,
        vin="JTDKN3DU0A0000006",
    )
    issued = await issue(invoice.id, db_session, settings, auth)
    invoice_read = await main.get_invoice_record(issued.id, db_session, auth)

    html = render_invoice_html(invoice_read, business_name=settings.business_name)
    pdf_text = extract_pdf_text(
        render_invoice_pdf(invoice_read, business_name=settings.business_name)
    )

    for marker in FORBIDDEN_MARKERS:
        assert marker not in html
        assert marker not in pdf_text


async def test_estimate_approval_public_view_excludes_forbidden_internal_fields(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    """Same forbidden-marker list, checked against the other customer-facing
    document surface in the app: the token-authenticated public approval
    view JSON payload. Largely overlaps
    `test_public_approval_view_excludes_internal_research_and_raw_overrides`
    in `tests/test_estimate_approval_api.py` -- kept for the same
    consolidated-scan reason as the invoice test above."""
    monkeypatch.setattr(
        main.OptimusResearchOrchestrator, "estimate_job", stub_sensitive_research_estimate_job
    )
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, _, estimate = await create_estimate_for_auth(
        settings, db_session, auth, vin="JTDKN3DU0A0000007"
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
    body = json.dumps(approval_view.model_dump(mode="json"))

    for marker in FORBIDDEN_MARKERS:
        assert marker not in body
