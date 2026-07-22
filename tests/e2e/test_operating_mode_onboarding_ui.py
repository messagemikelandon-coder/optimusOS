"""E2E coverage for the ADR-022 post-signup operating-mode onboarding card
(owner-only, non-blocking). Drives a real browser: a newly created shop's
owner sees the first-run card, previews and completes a mode (nav reshapes in
place), a confirmed shop's owner does not see it, managers/technicians never
see it and never call the owner-only endpoint, "Decide later" is non-blocking,
and a status-fetch failure fails open without claiming completion.
"""

from __future__ import annotations

from datetime import UTC, datetime

from playwright.sync_api import Page, expect
from sqlalchemy import delete, select

from app.auth import hash_password
from app.db import build_session_factory
from app.db_models import Shop, ShopMembership, UserAccount
from tests.e2e.conftest import LiveServer, SyntheticCredentials


def _owner_shop_id(database_url: str, owner_user_id: int) -> int:
    session_factory = build_session_factory(database_url)
    with session_factory() as db:
        shop_id = db.scalar(
            select(ShopMembership.shop_id).where(
                ShopMembership.user_account_id == owner_user_id,
                ShopMembership.role == "owner",
                ShopMembership.is_active.is_(True),
            )
        )
        assert shop_id is not None
        return shop_id


def _login(page: Page, live_server: LiveServer, username: str, password: str) -> None:
    page.goto(f"{live_server.base_url}/login")
    page.fill("#login-username", username)
    page.fill("#login-password", password)
    page.click("#login-submit")


def test_new_owner_sees_card_previews_and_completes(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    _login(page, live_server, synthetic_owner.username, synthetic_owner.password)
    expect(page.locator("#view-dashboard")).to_be_visible()

    # A brand-new shop is unconfirmed, so the first-run card appears.
    card = page.locator("#onboarding-mode-card")
    expect(card).to_be_visible()
    expect(page.locator('#sidebar [data-view="bays"]')).to_be_visible()

    # Preview Solo -> shows the hidden areas and the no-deletion wording.
    page.click('[data-onboard-mode="solo"]')
    expect(page.locator("#onboarding-preview")).to_be_visible()
    body = page.locator("#onboarding-preview-body")
    expect(body).to_contain_text("bays")
    expect(body).to_contain_text("tucked away")
    expect(page.locator("#onboarding-mode-card .mode-no-delete")).to_contain_text(
        "No data will be deleted"
    )

    # Confirm -> card disappears and nav reshapes in place (Bays hidden in Solo).
    page.click("#onboarding-confirm")
    expect(card).to_be_hidden()
    expect(page.locator('#sidebar [data-view="bays"]')).to_be_hidden()
    expect(page.locator('#sidebar [data-view="technicians"]')).to_be_hidden()


def test_confirmed_shop_owner_does_not_see_card(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    # Simulate an established/backfilled shop by stamping confirmation.
    shop_id = _owner_shop_id(live_server.database_url, synthetic_owner.user_id)
    session_factory = build_session_factory(live_server.database_url)
    with session_factory() as db:
        shop = db.get(Shop, shop_id)
        assert shop is not None
        shop.operating_mode_confirmed_at = datetime.now(UTC)
        db.commit()

    _login(page, live_server, synthetic_owner.username, synthetic_owner.password)
    expect(page.locator("#view-dashboard")).to_be_visible()
    # Give the status fetch time to resolve, then assert the card stays hidden.
    page.wait_for_timeout(600)
    expect(page.locator("#onboarding-mode-card")).to_be_hidden()


def test_decide_later_is_non_blocking(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    _login(page, live_server, synthetic_owner.username, synthetic_owner.password)
    expect(page.locator("#view-dashboard")).to_be_visible()
    card = page.locator("#onboarding-mode-card")
    expect(card).to_be_visible()

    # "Decide later" dismisses the card without blocking anything.
    page.click("#onboarding-later")
    expect(card).to_be_hidden()

    # Navigation still works, and the permanent change-later path (the System
    # bay mode panel) is available.
    page.click('#sidebar [data-view="customers"]')
    expect(page.locator("#view-customers")).to_be_visible()
    page.click('#sidebar [data-view="system"]')
    expect(page.locator("#operating-mode-panel")).to_be_visible()
    expect(card).to_be_hidden()


def test_technician_never_sees_card_or_calls_onboarding(
    page: Page, live_server: LiveServer, synthetic_technician: SyntheticCredentials
) -> None:
    onboarding_calls: list[str] = []
    page.on(
        "request",
        lambda req: (
            onboarding_calls.append(req.url)
            if "/api/operating-mode/onboarding" in req.url
            else None
        ),
    )
    _login(page, live_server, synthetic_technician.username, synthetic_technician.password)
    expect(page.locator("#view-my-day")).to_be_visible()
    page.wait_for_timeout(600)
    expect(page.locator("#onboarding-mode-card")).to_be_hidden()
    assert onboarding_calls == [], f"technician called onboarding: {onboarding_calls}"


def test_invited_manager_never_sees_card_or_calls_onboarding(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    onboarding_calls: list[str] = []
    page.on(
        "request",
        lambda req: (
            onboarding_calls.append(req.url)
            if "/api/operating-mode/onboarding" in req.url
            else None
        ),
    )

    shop_id = _owner_shop_id(live_server.database_url, synthetic_owner.user_id)
    session_factory = build_session_factory(live_server.database_url)
    manager_username = f"manager-onboard-{synthetic_owner.user_id}"
    manager_password = "manager-onboard-password-123"
    manager_id: int | None = None
    with session_factory() as db:
        manager = UserAccount(
            username=manager_username,
            display_name="Invited Manager",
            role="manager",
            shop_owner_id=synthetic_owner.user_id,
            password_hash=hash_password(manager_password),
            is_active=True,
        )
        db.add(manager)
        db.flush()
        manager_id = manager.id
        db.add(ShopMembership(shop_id=shop_id, user_account_id=manager.id, role="manager"))
        db.commit()

    try:
        _login(page, live_server, manager_username, manager_password)
        expect(page.locator("#view-dashboard")).to_be_visible()
        page.wait_for_timeout(600)
        # An invited manager must never see the owner-only first-run card...
        expect(page.locator("#onboarding-mode-card")).to_be_hidden()
        # ...and the frontend must not call the owner-only endpoint for them.
        assert onboarding_calls == [], f"manager called onboarding: {onboarding_calls}"
    finally:
        with session_factory() as db:
            db.execute(delete(ShopMembership).where(ShopMembership.user_account_id == manager_id))
            row = db.get(UserAccount, manager_id)
            if row is not None:
                db.delete(row)
            db.commit()


def test_onboarding_status_failure_fails_open(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    # Force the owner-only status endpoint to fail before login triggers it.
    page.route(
        "**/api/operating-mode/onboarding",
        lambda route: route.fulfill(
            status=503, content_type="application/json", body='{"detail":"down"}'
        ),
    )
    _login(page, live_server, synthetic_owner.username, synthetic_owner.password)
    expect(page.locator("#view-dashboard")).to_be_visible()
    page.wait_for_timeout(600)

    # Fail open: no card is shown (we never claim onboarding is complete), the
    # app is fully usable, and the permanent System-bay path still works.
    expect(page.locator("#onboarding-mode-card")).to_be_hidden()
    page.click('#sidebar [data-view="system"]')
    expect(page.locator("#operating-mode-panel")).to_be_visible()
