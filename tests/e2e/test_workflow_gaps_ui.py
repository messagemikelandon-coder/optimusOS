from __future__ import annotations

import re

import httpx
from playwright.sync_api import Page, expect
from sqlalchemy import select

from app.auth import hash_password
from app.db import build_session_factory
from app.db_models import ShopMembership, UserAccount
from tests.e2e.conftest import LiveServer, SyntheticCredentials


def test_workflow_gap_lifecycle_in_real_browser(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    console_messages: list[str] = []
    page.on(
        "console",
        lambda message: console_messages.append(message.text) if message.type == "error" else None,
    )
    page.goto(f"{live_server.base_url}/login")
    page.fill("#login-username", synthetic_owner.username)
    page.fill("#login-password", synthetic_owner.password)
    page.click("#login-submit")
    expect(page.locator("#view-dashboard")).to_be_visible()

    page.click('[data-view="workflow-gaps"]')
    expect(page.locator("#view-workflow-gaps")).to_be_visible()
    page.fill(
        "#workflow-gap-title",
        'Mobile inspection needs an offline fallback <img src=x onerror="window.gapXss=1">',
    )
    page.fill(
        "#workflow-gap-description",
        "A field inspection cannot be completed when the service area loses connectivity.",
    )
    page.fill("#workflow-gap-area", "inspections")
    page.select_option("#workflow-gap-severity", "high")
    page.fill("#workflow-gap-workaround", "Capture evidence locally and enter it at the shop.")
    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/workflow-gaps") and response.request.method == "POST"
        )
    ) as create_info:
        page.click("#workflow-gap-save")
    assert create_info.value.status == 200
    gap_id = create_info.value.json()["id"]
    expect(page.locator("#workflow-gap-form-mode")).to_have_text("EDIT")
    expect(page.locator("#workflow-gaps-list")).to_contain_text("offline fallback")
    expect(page.locator("#workflow-gaps-list img")).to_have_count(0)
    assert page.evaluate("() => window.gapXss") is None

    with page.expect_response(
        re.compile(rf"/api/workflow-gaps/{gap_id}/occurrences$")
    ) as count_info:
        page.click("#workflow-gap-occurrence")
    assert count_info.value.status == 200
    assert count_info.value.json()["occurrence_count"] == 2

    page.select_option("#workflow-gap-status", "investigating")
    with page.expect_response(
        lambda response: (
            response.url.endswith(f"/api/workflow-gaps/{gap_id}")
            and response.request.method == "PATCH"
        )
    ) as update_info:
        page.click("#workflow-gap-save")
    assert update_info.value.status == 200
    expect(page.locator("#workflow-gap-events")).to_contain_text("STATUS_CHANGED")
    expect(page.locator("#workflow-gap-events")).to_contain_text("Open → Investigating")

    page.select_option("#workflow-gaps-status-filter", "investigating")
    expect(page.locator("#workflow-gaps-list")).to_contain_text("offline fallback")
    page.select_option("#workflow-gaps-status-filter", "resolved")
    expect(page.locator("#workflow-gaps-list")).to_contain_text("No workflow gaps")
    page.select_option("#workflow-gaps-status-filter", "")
    expect(page.locator("#workflow-gaps-list")).to_contain_text("offline fallback")
    page.click("#workflow-gaps-new")
    expect(page.locator("#workflow-gap-events")).to_contain_text("Select a gap")
    expect(page.locator("#workflow-gaps-list .is-active")).to_have_count(0)

    second_response = httpx.post(
        f"{live_server.base_url}/api/test-support/synthetic-owner", timeout=10
    )
    second_response.raise_for_status()
    second_owner = second_response.json()
    try:
        page.click("#topbar-logout")
        expect(page.locator("#view-login")).to_be_visible()
        expect(page.locator("#workflow-gap-title")).to_have_value("")
        expect(page.locator("#workflow-gap-description")).to_have_value("")
        expect(page.locator("#workflow-gap-workaround")).to_have_value("")
        expect(page.locator("#workflow-gap-events")).to_contain_text(
            "Sign in to load workflow gaps."
        )

        page.fill("#login-username", second_owner["username"])
        page.fill("#login-password", second_owner["password"])
        page.click("#login-submit")
        expect(page.locator("#view-dashboard")).to_be_visible()
        page.click('[data-view="workflow-gaps"]')
        expect(page.locator("#workflow-gaps-list")).to_contain_text("No workflow gaps")
        expect(page.locator("#workflow-gap-title")).to_have_value("")
        expect(page.locator("#workflow-gap-events")).not_to_contain_text("Synthetic test owner")
        assert not any("content security policy" in item.lower() for item in console_messages)
    finally:
        cleanup_response = httpx.delete(
            f"{live_server.base_url}/api/test-support/synthetic-accounts/{second_owner['user_id']}",
            timeout=10,
        )
        cleanup_response.raise_for_status()


def test_manager_sees_workflow_gaps_and_technician_does_not(
    page: Page,
    live_server: LiveServer,
    synthetic_owner: SyntheticCredentials,
    synthetic_technician: SyntheticCredentials,
) -> None:
    session_factory = build_session_factory(live_server.database_url)
    manager_username = f"workflow-manager-{synthetic_owner.user_id}"
    manager_password = "workflow-manager-password-123"
    with session_factory() as db:
        owner = db.get(UserAccount, synthetic_owner.user_id)
        assert owner is not None
        membership = db.scalar(
            select(ShopMembership).where(ShopMembership.user_account_id == owner.id)
        )
        assert membership is not None
        manager = UserAccount(
            username=manager_username,
            display_name="Workflow Manager",
            role="manager",
            shop_owner_id=owner.id,
            password_hash=hash_password(manager_password),
            is_active=True,
            account_status="active",
        )
        db.add(manager)
        db.flush()
        db.add(
            ShopMembership(
                shop_id=membership.shop_id,
                user_account_id=manager.id,
                role="manager",
            )
        )
        db.commit()
        manager_id = manager.id

    try:
        page.goto(f"{live_server.base_url}/login")
        page.fill("#login-username", manager_username)
        page.fill("#login-password", manager_password)
        page.click("#login-submit")
        expect(page.locator("#view-dashboard")).to_be_visible()
        expect(page.locator('[data-view="workflow-gaps"]')).to_be_visible()
        page.click('[data-view="workflow-gaps"]')
        expect(page.locator("#view-workflow-gaps")).to_be_visible()
        page.click("#topbar-logout")

        page.fill("#login-username", synthetic_technician.username)
        page.fill("#login-password", synthetic_technician.password)
        page.click("#login-submit")
        expect(page.locator("#view-my-day")).to_be_visible()
        expect(page.locator('[data-view="workflow-gaps"]')).to_be_hidden()
    finally:
        with session_factory() as db:
            manager = db.get(UserAccount, manager_id)
            if manager is not None:
                db.delete(manager)
                db.commit()
