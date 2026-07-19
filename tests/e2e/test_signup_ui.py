from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e.conftest import LiveServer


def test_signup_form_creates_shop_and_logs_in_via_real_browser(
    page: Page, live_server: LiveServer
) -> None:
    """Real browser, real session cookie, real Postgres-backed API call --
    no client-side auth-state bypass. Proves the new self-service /signup
    form (added alongside the /goal Phase 4 slice 1 backend route) actually
    creates a shop and logs its owner in through the real UI, not just via
    a direct API call (already covered by tests/e2e/test_signup_e2e.py)."""
    unique = str(id(page))
    business_name = f"Rivera Auto Repair {unique}"
    username = f"alex.rivera.{unique}"
    email = f"alex.rivera.{unique}@example.com"

    page.goto(f"{live_server.base_url}/signup")
    expect(page.locator("#view-signup")).to_be_visible()

    page.fill("#signup-business-name", business_name)
    page.fill("#signup-owner-display-name", "Alex Rivera")
    page.fill("#signup-username", username)
    page.fill("#signup-email", email)
    page.fill("#signup-password", "a-real-password-123")
    with page.expect_response(re.compile(r"/api/signup$")) as response_info:
        page.click("#signup-submit")
    response = response_info.value
    assert response.status == 200
    assert response.json()["user"]["role"] == "owner"

    expect(page.locator("#view-dashboard")).to_be_visible()
    expect(page.locator("#operator-name")).to_have_text("Alex Rivera")

    # The signup form's own session cookie (not injected state) authenticates
    # a real subsequent UI action, proving the login-on-signup flow is a
    # genuine, working session -- not just a client-side auth flag flip.
    page.click('[data-view="customers"]')
    expect(page.locator("#customer-form")).to_be_visible()
    page.fill("#customer-first-name", "Real")
    page.fill("#customer-last-name", "Customer")
    with page.expect_response(re.compile(r"/api/customers$")) as customer_response_info:
        page.click("#customer-save")
    assert customer_response_info.value.status == 200


def test_signup_and_login_views_cross_link_to_each_other(
    page: Page, live_server: LiveServer
) -> None:
    """The signup/login forms link to each other so a visitor who lands on
    the wrong one isn't stuck re-typing the URL by hand."""
    page.goto(f"{live_server.base_url}/login")
    expect(page.locator("#view-login")).to_be_visible()
    page.click('#view-login [data-view="signup"]')
    expect(page.locator("#view-signup")).to_be_visible()
    assert page.url.endswith("/signup")

    page.click('#view-signup [data-view="login"]')
    expect(page.locator("#view-login")).to_be_visible()
    assert page.url.endswith("/login")
