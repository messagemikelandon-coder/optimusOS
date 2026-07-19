from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from playwright.sync_api import Page, expect
from sqlalchemy import select

from app.db import build_session_factory
from app.db_models import PasswordResetToken, ShopInvitation, UserAccount
from tests.e2e.conftest import LiveServer, SyntheticCredentials


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_account_security_and_invitation_workflows_in_real_browser(
    page: Page,
    live_server: LiveServer,
    synthetic_owner: SyntheticCredentials,
) -> None:
    page.goto(f"{live_server.base_url}/login")
    page.fill("#login-username", synthetic_owner.username)
    page.fill("#login-password", synthetic_owner.password)
    page.click("#login-submit")
    expect(page.locator("#view-dashboard")).to_be_visible()

    page.click('[data-view="system"]')
    expect(page.locator("#view-system")).to_be_visible()
    expect(page.locator("#account-session-list [data-revoke-session]")).to_have_count(1)
    expect(page.locator("#account-login-history")).to_contain_text("SUCCEEDED")
    expect(page.locator("#account-mfa-status")).to_have_text("MFA-ready")

    changed_password = "browser-changed-password-123"
    page.fill("#account-current-password", synthetic_owner.password)
    page.fill("#account-new-password", changed_password)
    with page.expect_response(re.compile(r"/api/auth/password/change$")) as change_info:
        page.click("#account-password-submit")
    assert change_info.value.status == 200

    browser = page.context.browser
    assert browser is not None
    secondary_owner_context = browser.new_context()
    secondary_owner_page = secondary_owner_context.new_page()
    try:
        secondary_owner_page.goto(f"{live_server.base_url}/login")
        secondary_owner_page.fill("#login-username", synthetic_owner.username)
        secondary_owner_page.fill("#login-password", changed_password)
        secondary_owner_page.click("#login-submit")
        expect(secondary_owner_page.locator("#view-dashboard")).to_be_visible()
        with page.expect_response(re.compile(r"/api/auth/sessions/revoke-others$")) as revoke_info:
            page.click("#account-revoke-others")
        assert revoke_info.value.status == 200
        assert revoke_info.value.json()["revoked"] == 1
        assert (
            secondary_owner_page.evaluate("async () => (await fetch('/api/auth/me')).status") == 401
        )
    finally:
        secondary_owner_context.close()

    invited_email = f"browser.manager.{id(page)}@example.com"
    page.fill("#shop-invitation-email", invited_email)
    page.select_option("#shop-invitation-role", "manager")
    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/shop/invitations") and response.request.method == "POST"
        )
    ) as invite_info:
        page.click("#shop-invitation-submit")
    assert invite_info.value.status == 200
    invitation_id = invite_info.value.json()["id"]
    raw_invitation_token = "browser-account-lifecycle-invitation-token"
    with build_session_factory(live_server.database_url)() as db:
        invitation = db.get(ShopInvitation, invitation_id)
        assert invitation is not None
        invitation.token_hash = _hash_token(raw_invitation_token)
        db.add(invitation)
        db.commit()

    invited_context = browser.new_context()
    invited_page = invited_context.new_page()
    try:
        invited_page.goto(f"{live_server.base_url}/accept-invitation")
        expect(invited_page.locator("#view-accept-invitation")).to_be_visible()
        invited_page.fill("#accept-invitation-token", raw_invitation_token)
        invited_page.fill("#accept-invitation-name", "Browser Manager")
        invited_page.fill("#accept-invitation-username", f"browser-manager-{id(page)}")
        invited_page.fill("#accept-invitation-password", "browser-manager-password-123")
        with invited_page.expect_response(re.compile(r"/api/invitations/accept$")) as accept_info:
            invited_page.click("#accept-invitation-submit")
        assert accept_info.value.status == 200
        manager_id = accept_info.value.json()["user"]["id"]
        expect(invited_page.locator("#view-login")).to_be_visible()
        invited_page.fill("#login-username", f"browser-manager-{id(page)}")
        invited_page.fill("#login-password", "browser-manager-password-123")
        invited_page.click("#login-submit")
        expect(invited_page.locator("#view-dashboard")).to_be_visible()
        invited_page.click('[data-view="system"]')
        expect(invited_page.locator("#account-password-form")).to_be_visible()
        expect(invited_page.locator("#account-session-list [data-revoke-session]")).to_have_count(1)
        expect(invited_page.locator("#shop-invitation-form")).to_be_visible()
        expect(
            invited_page.locator('#shop-invitation-role option[value="owner"]')
        ).to_have_attribute("disabled", "")
        expect(
            invited_page.locator('#shop-invitation-role option[value="manager"]')
        ).to_have_attribute("disabled", "")

        page.reload()
        expect(page.locator("#view-dashboard")).to_be_visible()
        page.click('[data-view="system"]')
        member_status = page.locator(f'[data-member-status="{manager_id}"]')
        expect(member_status).to_be_visible()
        with page.expect_response(
            re.compile(rf"/api/shop/members/{manager_id}/status$")
        ) as status_info:
            member_status.select_option("suspended")
        assert status_info.value.status == 200
        assert invited_page.evaluate("async () => (await fetch('/api/auth/me')).status") == 401
        invited_page.goto(f"{live_server.base_url}/login")
        invited_page.fill("#login-username", f"browser-manager-{id(page)}")
        invited_page.fill("#login-password", "browser-manager-password-123")
        with invited_page.expect_response(re.compile(r"/api/auth/login$")) as blocked_info:
            invited_page.click("#login-submit")
        assert blocked_info.value.status == 401
    finally:
        invited_context.close()

    page.fill("#shop-invitation-email", f"revoked.{id(page)}@example.com")
    page.select_option("#shop-invitation-role", "technician")
    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/shop/invitations") and response.request.method == "POST"
        )
    ) as revoke_invite_create:
        page.click("#shop-invitation-submit")
    assert revoke_invite_create.value.status == 200
    with page.expect_response(re.compile(r"/api/shop/invitations/\d+/revoke$")) as revoke_invite:
        page.locator("#shop-invitation-list [data-revoke-invitation]").first.click()
    assert revoke_invite.value.status == 200
    expect(page.locator("#shop-invitation-list")).to_contain_text("Revoked")

    technician_email = f"browser.tech.{id(page)}@example.com"
    page.fill("#shop-invitation-email", technician_email)
    page.select_option("#shop-invitation-role", "technician")
    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/shop/invitations") and response.request.method == "POST"
        )
    ) as technician_invite_info:
        page.click("#shop-invitation-submit")
    technician_invitation_id = technician_invite_info.value.json()["id"]
    raw_technician_token = "browser-technician-invitation-token"
    with build_session_factory(live_server.database_url)() as db:
        invitation = db.get(ShopInvitation, technician_invitation_id)
        assert invitation is not None
        invitation.token_hash = _hash_token(raw_technician_token)
        db.add(invitation)
        db.commit()

    technician_context = browser.new_context()
    technician_page = technician_context.new_page()
    try:
        technician_page.goto(f"{live_server.base_url}/accept-invitation")
        technician_page.fill("#accept-invitation-token", raw_technician_token)
        technician_page.fill("#accept-invitation-name", "Browser Technician")
        technician_page.fill("#accept-invitation-username", f"browser-tech-{id(page)}")
        technician_page.fill("#accept-invitation-password", "browser-tech-password-123")
        technician_page.click("#accept-invitation-submit")
        expect(technician_page.locator("#view-login")).to_be_visible()
        technician_page.fill("#login-username", f"browser-tech-{id(page)}")
        technician_page.fill("#login-password", "browser-tech-password-123")
        technician_page.click("#login-submit")
        expect(technician_page.locator("#view-my-day")).to_be_visible()
        technician_page.click('[data-view="system"]')
        expect(technician_page.locator("#account-password-form")).to_be_visible()
        expect(technician_page.locator("#shop-invitation-form")).to_be_hidden()
        with technician_page.expect_response(
            re.compile(r"/api/auth/sessions/\d+/revoke$")
        ) as technician_revoke:
            technician_page.locator("#account-session-list [data-revoke-session]").click()
        assert technician_revoke.value.status == 200
        expect(technician_page.locator("#view-login")).to_be_visible()
    finally:
        technician_context.close()

    owner_email = f"browser.owner.{id(page)}@example.com"
    with build_session_factory(live_server.database_url)() as db:
        owner = db.get(UserAccount, synthetic_owner.user_id)
        assert owner is not None
        owner.email = owner_email
        owner.email_normalized = owner_email
        owner.email_verified_at = datetime.now(UTC)
        db.add(owner)
        db.commit()

    page.goto(f"{live_server.base_url}/forgot-password")
    expect(page.locator("#view-forgot-password")).to_be_visible()
    page.fill("#forgot-password-email", owner_email)
    with page.expect_response(re.compile(r"/api/auth/password/reset-request$")) as request_info:
        page.click("#forgot-password-submit")
    assert request_info.value.status == 200
    expect(page.locator("#view-reset-password")).to_be_visible()

    raw_reset_token = "browser-account-lifecycle-reset-token"
    with build_session_factory(live_server.database_url)() as db:
        reset = db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.user_account_id == synthetic_owner.user_id,
                PasswordResetToken.status == "active",
            )
        )
        assert reset is not None
        reset.token_hash = _hash_token(raw_reset_token)
        db.add(reset)
        db.commit()

    final_password = "browser-reset-password-456"
    page.fill("#reset-password-token", raw_reset_token)
    page.fill("#reset-password-new", final_password)
    with page.expect_response(re.compile(r"/api/auth/password/reset-confirm$")) as reset_info:
        page.click("#reset-password-submit")
    assert reset_info.value.status == 200
    expect(page.locator("#view-login")).to_be_visible()
    page.fill("#login-username", synthetic_owner.username)
    page.fill("#login-password", final_password)
    with page.expect_response(re.compile(r"/api/auth/login$")) as relogin_info:
        page.click("#login-submit")
    assert relogin_info.value.status == 200
    expect(page.locator("#view-dashboard")).to_be_visible()
