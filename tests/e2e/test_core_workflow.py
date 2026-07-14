from __future__ import annotations

import re

from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from sqlalchemy.orm import sessionmaker

from app.db import build_engine
from tests.e2e.conftest import LiveServer, SyntheticCredentials
from tests.e2e.seed import seed_ready_estimate


def _login(page: Page, live_server: LiveServer, creds: SyntheticCredentials) -> None:
    page.goto(f"{live_server.base_url}/login")
    page.fill("#login-username", creds.username)
    page.fill("#login-password", creds.password)
    with page.expect_response(re.compile(r"/api/auth/login$")) as response_info:
        page.click("#login-submit")
    assert response_info.value.status == 200


def test_core_repair_workflow_end_to_end(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    """Real browser, real session cookie, real Postgres-backed API calls
    throughout -- no client-side auth-state bypass. Walks the full
    customer -> vehicle -> estimate -> approval -> work order -> completion
    -> invoice -> payment chain and asserts the real balance/status at the
    end."""
    console_errors: list[str] = []
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )

    # --- Login (real session cookie, not injected frontend state) ---
    _login(page, live_server, synthetic_owner)
    expect(page.locator("#view-dashboard")).to_be_visible()

    # --- Create customer ---
    page.click('[data-view="customers"]')
    expect(page.locator("#customer-form")).to_be_visible()
    page.fill("#customer-first-name", "Jordan")
    page.fill("#customer-last-name", "Rivera")
    page.fill("#customer-email", "jordan.rivera@example.com")
    page.fill("#customer-phone", "555-201-4477")
    with page.expect_response(re.compile(r"/api/customers$")) as customer_response_info:
        page.click("#customer-save")
    customer_response = customer_response_info.value
    assert customer_response.status == 200
    customer_id = customer_response.json()["id"]

    # --- Create vehicle under that customer ---
    page.click('[data-view="vehicles"]')
    expect(page.locator("#vehicle-form")).to_be_visible()
    # The customer dropdown is populated asynchronously (loadCustomerOptions,
    # fired at the end of the customer-save handler); wait for the real
    # option and verify the selection actually stuck before proceeding.
    expect(page.locator(f'#vehicle-customer-id option[value="{customer_id}"]')).to_have_count(1)
    for _attempt in range(10):
        page.select_option("#vehicle-customer-id", value=str(customer_id))
        if page.eval_on_selector("#vehicle-customer-id", "el => el.value") == str(customer_id):
            break
        page.wait_for_timeout(200)
    else:
        raise AssertionError("Could not get #vehicle-customer-id selection to stick.")
    page.fill("#vehicle-year", "2019")
    page.fill("#vehicle-make", "Honda")
    page.fill("#vehicle-model", "Civic")
    with page.expect_response(
        re.compile(rf"/api/customers/{customer_id}/vehicles$")
    ) as vehicle_response_info:
        page.click("#vehicle-save")
    vehicle_response = vehicle_response_info.value
    assert vehicle_response.status == 200
    vehicle_id = vehicle_response.json()["id"]

    # --- Seed a real, complete "ready" estimate directly via the ORM,
    # reusing this repo's existing deterministic non-billable research
    # fixture (scripts/seed_estimate_approval_fixture.py). The real estimate
    # *creation* form triggers a real, billable OpenAI research call --
    # every other step below (opening the estimate, sending for approval,
    # approving, converting to a work order, completion, invoicing,
    # payment) drives the real UI and real API exactly as a user would. ---
    engine = build_engine(live_server.database_url)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as seed_session:
        estimate_id = seed_ready_estimate(
            seed_session,
            owner_id=synthetic_owner.user_id,
            customer_id=customer_id,
            vehicle_id=vehicle_id,
        )

    # --- Open the seeded estimate through the real UI (Customer History's
    # "open estimate" link, the same path a real owner would use) ---
    page.click('[data-view="customers"]')
    page.click(f'[data-customer-id="{customer_id}"]')
    with page.expect_response(re.compile(rf"/api/estimates/{estimate_id}$")) as open_estimate_info:
        page.click(f'[data-history-estimate-id="{estimate_id}"]')
    assert open_estimate_info.value.status == 200

    # --- Send for approval and capture the real approval link ---
    with page.expect_response(
        re.compile(rf"/api/estimates/{estimate_id}/send-for-approval$")
    ) as approval_link_response_info:
        page.click("#send-estimate-approval")
    approval_link_response = approval_link_response_info.value
    assert approval_link_response.status == 200
    approval_link = approval_link_response.json()["approval_link"]

    # --- Approve as the customer, via the real public approval link (a
    # separate, unauthenticated browser context -- proves the token-based
    # flow works independently of the owner's session) ---
    approval_page = page.context.new_page()
    approval_page.goto(f"{live_server.base_url}{approval_link}")
    expect(approval_page.locator("#approval-action-form")).to_be_visible()
    approval_page.fill("#approval-name", "Jordan Rivera")
    approval_page.fill("#approval-typed-authorization", "Jordan Rivera approves this estimate.")
    approval_page.check("#approval-accept-terms")
    with approval_page.expect_response(
        re.compile(r"/api/estimate-approval/approve$")
    ) as approve_response_info:
        approval_page.click('#approval-action-form button[type="submit"]')
    approve_response = approve_response_info.value
    assert approve_response.status == 200, approve_response.text()
    approval_page.close()

    # --- Back in the owner session: the page still holds the pre-approval
    # client state, so explicitly refresh the record (the real "Refresh
    # status" action) before the now-enabled "Create work order" button
    # reflects the real server-side approved status ---
    page.click('[data-view="estimate"]')
    with page.expect_response(re.compile(rf"/api/estimates/{estimate_id}$")) as refresh_info:
        page.click("#refresh-estimate-record")
    assert refresh_info.value.json()["status"] == "approved"

    with page.expect_response(
        re.compile(rf"/api/estimates/{estimate_id}/work-order$")
    ) as work_order_response_info:
        page.click("#create-work-order")
    work_order_response = work_order_response_info.value
    assert work_order_response.status == 200, work_order_response.text()
    work_order_id = work_order_response.json()["id"]
    assert work_order_response.json()["status"] == "ready_to_schedule"

    # --- Walk the work order through to completion ---
    page.goto(f"{live_server.base_url}/")
    page.click('[data-view="work-orders"]')
    with page.expect_response(
        re.compile(rf"/api/work-orders/{work_order_id}$")
    ) as work_order_detail_info:
        page.click(f'[data-work-order-id="{work_order_id}"]')
    assert work_order_detail_info.value.status == 200
    expect(page.locator("#work-order-status-form")).to_be_visible()

    invoice_id: int | None = None
    for next_status in ("scheduled", "in_progress", "completed"):
        # The next-status <select> is rebuilt asynchronously, and a second,
        # fire-and-forget re-render can land in the gap between selecting
        # and clicking Save, silently resetting the value back to empty
        # (the handler no-ops with a toast rather than erroring). Retry the
        # whole select+click+response sequence rather than trusting one
        # attempt to win the race.
        status_response = None
        for _attempt in range(8):
            expect(
                page.locator(f'#work-order-next-status option[value="{next_status}"]')
            ).to_have_count(1)
            page.select_option("#work-order-next-status", value=next_status)
            try:
                with page.expect_response(
                    re.compile(rf"/api/work-orders/{work_order_id}/status$"), timeout=2000
                ) as status_response_info:
                    page.click("#work-order-status-save")
                status_response = status_response_info.value
                break
            except PlaywrightTimeoutError:
                continue
        assert status_response is not None, (
            f"Status update to {next_status!r} never fired a request after 8 attempts."
        )
        assert status_response.status == 200, status_response.text()
        status_body = status_response.json()
        assert status_body["status"] == next_status
        if next_status == "completed":
            invoice_id = status_body["invoice_id"]
        # The status handler also fires a fire-and-forget work-order-list
        # refresh that re-renders this same detail panel a second time;
        # let it settle before the next iteration selects an option, or the
        # second render can silently clobber the just-made selection.
        page.wait_for_load_state("networkidle")
    assert invoice_id is not None, "Completion should atomically create a draft invoice."

    # --- Open the auto-generated draft invoice and issue it ---
    with page.expect_response(re.compile(rf"/api/invoices/{invoice_id}$")) as invoice_lookup_info:
        page.click("#work-order-open-invoice")
    invoice_lookup = invoice_lookup_info.value
    assert invoice_lookup.status == 200

    expect(page.locator("#invoice-issue-form")).to_be_visible()
    with page.expect_response(
        re.compile(rf"/api/invoices/{invoice_id}/issue$")
    ) as issue_response_info:
        page.click("#invoice-issue-save")
    issue_response = issue_response_info.value
    assert issue_response.status == 200, issue_response.text()
    invoice_total = issue_response.json()["invoice_total"]

    # --- Record full payment and verify the real computed balance/status ---
    page.fill("#invoice-payment-amount", str(invoice_total))
    page.fill("#invoice-payment-method", "Cash")
    with page.expect_response(
        re.compile(rf"/api/invoices/{invoice_id}/payments$")
    ) as payment_response_info:
        page.click("#invoice-payment-save")
    payment_response = payment_response_info.value
    assert payment_response.status == 200, payment_response.text()
    payment_body = payment_response.json()
    assert payment_body["status"] == "paid"
    assert float(payment_body["balance_due"]) == 0.0

    unexpected_console_errors = [
        error for error in console_errors if "401" not in error and "Unauthorized" not in error
    ]
    assert unexpected_console_errors == [], unexpected_console_errors
