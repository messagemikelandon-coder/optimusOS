from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.conftest import LiveServer, SyntheticCredentials


def test_billing_panel_shows_real_subscription_state_in_a_real_browser(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    page.goto(f"{live_server.base_url}/login")
    page.fill("#login-username", synthetic_owner.username)
    page.fill("#login-password", synthetic_owner.password)
    page.click("#login-submit")
    expect(page.locator("#view-dashboard")).to_be_visible()

    page.click('[data-view="system"]')
    expect(page.locator("#view-system")).to_be_visible()
    # The synthetic owner is grandfathered onto the unlimited-seat tier at
    # creation time (app/shop_store.py::create_shop_for_new_owner), same as
    # the real pilot shop -- never a real trial countdown.
    expect(page.locator("#billing-status-title")).to_contain_text("Shop")
    expect(page.locator("#billing-status-title")).to_contain_text("active")
    expect(page.locator("#billing-status-detail")).to_contain_text("technician seat(s) used")
    expect(page.locator("#billing-payment-status")).to_have_text("No payment method on file.")

    # This environment has no real Square sandbox credentials configured --
    # a disclosed, honest limitation (see docs/context/KNOWN_ISSUES.md).
    # Clicking the sandbox-test-card action must fail cleanly, not crash the
    # page or silently pretend to succeed.
    with page.expect_response(re.compile(r"/api/billing/payment-method$")) as payment_method_info:
        page.click("#billing-add-payment-method")
    assert payment_method_info.value.status == 503
    expect(page.locator(".toast.error")).to_contain_text("Square is not configured")


def test_technician_does_not_see_the_billing_panel(
    page: Page, live_server: LiveServer, synthetic_technician: SyntheticCredentials
) -> None:
    page.goto(f"{live_server.base_url}/login")
    page.fill("#login-username", synthetic_technician.username)
    page.fill("#login-password", synthetic_technician.password)
    page.click("#login-submit")
    expect(page.locator("#view-my-day")).to_be_visible()

    page.click('[data-view="system"]')
    expect(page.locator("#view-system")).to_be_visible()
    expect(page.locator("#billing-status-title")).to_be_hidden()
