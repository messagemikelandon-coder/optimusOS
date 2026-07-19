from __future__ import annotations

import re

from playwright.sync_api import Page, expect
from sqlalchemy import select

from app.auth import hash_password
from app.db import build_session_factory
from app.db_models import UserAccount
from tests.e2e.conftest import LiveServer, SyntheticCredentials


def test_support_session_sees_only_the_shop_directory_in_a_real_browser(
    page: Page,
    live_server: LiveServer,
    synthetic_owner: SyntheticCredentials,
) -> None:
    session_factory = build_session_factory(live_server.database_url)
    support_username = f"support-{synthetic_owner.user_id}"
    support_password = "support-directory-password-123"
    with session_factory() as db:
        existing = db.scalar(select(UserAccount).where(UserAccount.username == support_username))
        assert existing is None
        support_user = UserAccount(
            username=support_username,
            display_name="Support",
            role="support",
            password_hash=hash_password(support_password),
            is_active=True,
        )
        db.add(support_user)
        db.commit()
        support_user_id = support_user.id

    try:
        page.goto(f"{live_server.base_url}/login")
        page.fill("#login-username", support_username)
        page.fill("#login-password", support_password)
        page.click("#login-submit")
        expect(page.locator("#view-support-directory")).to_be_visible()
        # No business-data nav destinations must be reachable -- only the
        # dedicated support-only one. Scoped to the sidebar since both the
        # desktop and mobile bottom nav have a matching button.
        expect(page.locator('#sidebar [data-view="dashboard"]')).to_be_hidden()
        expect(page.locator('#sidebar [data-view="customers"]')).to_be_hidden()
        expect(page.locator('#sidebar [data-view="system"]')).to_be_hidden()
        expect(page.locator('#sidebar [data-view="support-directory"]')).to_be_visible()
        expect(page.locator("#support-directory-list")).to_contain_text("Landon Motor Works")

        # A direct API call from this same real session proves the backend
        # gate, not just that the frontend hid the nav item.
        blocked_status = page.evaluate("async () => (await fetch('/api/customers')).status")
        assert blocked_status == 403
    finally:
        with session_factory() as db:
            leftover = db.get(UserAccount, support_user_id)
            if leftover is not None:
                db.delete(leftover)
                db.commit()


def test_support_can_impersonate_a_shop_owner_and_end_it_in_a_real_browser(
    page: Page,
    live_server: LiveServer,
    synthetic_owner: SyntheticCredentials,
) -> None:
    session_factory = build_session_factory(live_server.database_url)
    support_username = f"support-impersonate-{synthetic_owner.user_id}"
    support_password = "support-impersonate-password-123"
    with session_factory() as db:
        support_user = UserAccount(
            username=support_username,
            display_name="Support",
            role="support",
            password_hash=hash_password(support_password),
            is_active=True,
        )
        db.add(support_user)
        db.commit()
        support_user_id = support_user.id

    try:
        page.goto(f"{live_server.base_url}/login")
        page.fill("#login-username", support_username)
        page.fill("#login-password", support_password)
        page.click("#login-submit")
        expect(page.locator("#view-support-directory")).to_be_visible()

        # Impersonation now asks for a native confirm() before firing the
        # request (independent-review hardening) -- accept it here the same
        # way a real support user would.
        page.on("dialog", lambda dialog: dialog.accept())
        with page.expect_response(
            lambda response: "/impersonate" in response.url and response.request.method == "POST"
        ) as impersonate_info:
            page.click("[data-impersonate-shop]")
        assert impersonate_info.value.status == 200
        assert impersonate_info.value.json()["user"]["role"] == "owner"

        expect(page.locator("#view-dashboard")).to_be_visible()
        expect(page.locator("#impersonation-banner")).to_be_visible()
        expect(page.locator("#impersonation-support-name")).to_have_text(support_username)

        # The impersonated session is a real owner session -- it can
        # actually create a real customer, not just view a read-only page.
        page.click('[data-view="customers"]')
        expect(page.locator("#customer-form")).to_be_visible()
        page.fill("#customer-first-name", "Impersonated")
        page.fill("#customer-last-name", "Write")
        with page.expect_response(re.compile(r"/api/customers$")) as create_info:
            page.click("#customer-save")
        assert create_info.value.status == 200

        with page.expect_response(
            lambda response: response.url.endswith("/api/support/end-impersonation")
        ) as end_info:
            page.click("#impersonation-end")
        assert end_info.value.status == 200
        assert end_info.value.json()["user"]["role"] == "support"

        expect(page.locator("#view-support-directory")).to_be_visible()
        expect(page.locator("#impersonation-banner")).to_be_hidden()
        blocked_status = page.evaluate("async () => (await fetch('/api/customers')).status")
        assert blocked_status == 403
    finally:
        with session_factory() as db:
            leftover = db.get(UserAccount, support_user_id)
            if leftover is not None:
                db.delete(leftover)
                db.commit()
