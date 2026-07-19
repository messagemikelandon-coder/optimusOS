from __future__ import annotations

import re

import httpx
from playwright.sync_api import Page, expect

from app.db import build_session_factory
from tests.e2e.conftest import LiveServer
from tests.e2e.seed import set_email_verification_token_for_test


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
    signup_body = response.json()
    assert signup_body["user"]["role"] == "owner"

    expect(page.locator("#view-verify-email")).to_be_visible()
    expect(page.locator("#operator-name")).to_have_text("Alex Rivera")

    blocked_status = page.evaluate(
        """async () => (await fetch('/api/customers', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({first_name: 'Blocked', last_name: 'Before Verification'})
        })).status"""
    )
    assert blocked_status == 403

    raw_token = "browser-email-verification-token"
    with build_session_factory(live_server.database_url)() as db:
        set_email_verification_token_for_test(
            db, user_id=signup_body["user"]["id"], raw_token=raw_token
        )
    page.fill("#verify-email-token", raw_token)
    with page.expect_response(re.compile(r"/api/auth/verify-email$")) as verify_response_info:
        page.click("#verify-email-submit")
    assert verify_response_info.value.status == 200
    # /goal Phase 7: a fresh signup lands on the "choose your plan" onboarding
    # step (14-day trial already running) before the dashboard, not straight
    # into it.
    expect(page.locator("#view-choose-plan")).to_be_visible()
    expect(page.locator("#choose-plan-status-title")).to_contain_text("No payment method")
    page.click("#choose-plan-skip")
    expect(page.locator("#view-dashboard")).to_be_visible()

    # The signup form's own session cookie (not injected state) authenticates
    # a real subsequent UI action after mailbox proof, proving both the
    # session and verification gate are real server-side controls.
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


def test_email_verification_page_works_without_an_existing_session(
    page: Page, live_server: LiveServer
) -> None:
    unique = str(id(page))
    signup_response = httpx.post(
        f"{live_server.base_url}/api/signup",
        json={
            "business_name": f"Fresh Browser Shop {unique}",
            "owner_display_name": "Fresh Browser Owner",
            "username": f"fresh.browser.{unique}",
            "email": f"fresh.browser.{unique}@example.com",
            "password": "a-real-password-123",
        },
        timeout=10,
    )
    signup_response.raise_for_status()

    raw_token = "fresh-browser-email-verification-token"
    with build_session_factory(live_server.database_url)() as db:
        set_email_verification_token_for_test(
            db, user_id=signup_response.json()["user"]["id"], raw_token=raw_token
        )

    browser = page.context.browser
    assert browser is not None
    fresh_context = browser.new_context()
    verification_page = fresh_context.new_page()
    try:
        verification_page.goto(f"{live_server.base_url}/verify-email")
        expect(verification_page.locator("#view-verify-email")).to_be_visible()
        verification_page.fill("#verify-email-token", raw_token)
        with verification_page.expect_response(
            re.compile(r"/api/auth/verify-email$")
        ) as response_info:
            verification_page.click("#verify-email-submit")
        assert response_info.value.status == 200
        expect(verification_page.locator("#view-login")).to_be_visible()
    finally:
        fresh_context.close()
