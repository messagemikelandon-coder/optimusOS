"""E2E coverage for the ADR-022 operating-mode management UI and
capability-shaped navigation (owner/manager only). Drives a real browser
against the real app: previews and applies a mode change, verifies the nav
reshapes in place, verifies role/capability layering, stale-conflict
recovery, fail-open behavior, and that no route or enforcement changed.

Everything here is frontend behavior over the existing capability and
mode-transition APIs -- these tests assert the UI never enforces (backend
routes stay reachable regardless of what the nav shows).
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
from sqlalchemy import select

from app.auth import hash_password
from app.db import build_session_factory
from app.db_models import UserAccount
from tests.e2e.conftest import LiveServer, SyntheticCredentials


def _login(page: Page, live_server: LiveServer, creds: SyntheticCredentials) -> None:
    page.goto(f"{live_server.base_url}/login")
    page.fill("#login-username", creds.username)
    page.fill("#login-password", creds.password)
    page.click("#login-submit")


def _create_bay(page: Page, name: str = "Bay A") -> None:
    status = page.evaluate(
        """async (name) => {
            const r = await fetch('/api/bays', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ name }),
            });
            return r.status;
        }""",
        name,
    )
    assert status < 300, f"bay creation failed with {status}"


def test_owner_previews_and_applies_a_mode_change_that_reshapes_nav_in_place(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    _login(page, live_server, synthetic_owner)
    expect(page.locator("#view-dashboard")).to_be_visible()
    # A synthetic owner is created in the default `shop` operating mode, so
    # every capability is full and Bays + Technicians are surfaced.
    expect(page.locator('#sidebar [data-view="bays"]')).to_be_visible()
    expect(page.locator('#sidebar [data-view="technicians"]')).to_be_visible()

    # Real existing data so the preview surfaces a retained-data warning.
    _create_bay(page)

    page.click('#sidebar [data-view="system"]')
    expect(page.locator("#view-system")).to_be_visible()
    expect(page.locator("#operating-mode-panel")).to_be_visible()
    expect(page.locator("#operating-mode-current")).to_contain_text("Shop mode")

    # Preview the Shop -> Solo switch (read-only dry run).
    page.click('[data-mode-preview="solo"]')
    expect(page.locator("#operating-mode-preview")).to_be_visible()
    body = page.locator("#operating-mode-preview-body")
    # Capability changes + would-be-hidden areas.
    expect(body).to_contain_text("bays")
    expect(body).to_contain_text("technicians")
    # Retained-data warning with a real count, and the explicit no-delete line.
    expect(body).to_contain_text("bays record(s)")
    expect(body).to_contain_text("retained")
    expect(page.locator(".mode-no-delete")).to_contain_text("No data will be deleted")

    # Confirm and apply. Nav reshapes without any full-page reload.
    page.click("#operating-mode-confirm")
    expect(page.locator("#operating-mode-current")).to_contain_text("Solo mode")
    # Solo hides Bays and Technicians...
    expect(page.locator('#sidebar [data-view="bays"]')).to_be_hidden()
    expect(page.locator('#sidebar [data-view="technicians"]')).to_be_hidden()
    # ...but LIMITED capabilities (scheduling, reports in Solo) stay visible.
    expect(page.locator('#sidebar [data-view="scheduling"]')).to_be_visible()
    expect(page.locator('#sidebar [data-view="reports"]')).to_be_visible()
    expect(page.locator("#operating-mode-status")).to_contain_text("nothing was deleted")


def test_bays_nav_follows_the_mode_across_solo_mobile_field_and_shop(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    _login(page, live_server, synthetic_owner)
    expect(page.locator("#view-dashboard")).to_be_visible()
    page.click('#sidebar [data-view="system"]')
    expect(page.locator("#operating-mode-panel")).to_be_visible()

    bays_desktop = page.locator('#sidebar [data-view="bays"]')
    bays_mobile = page.locator('.mobile-bottom-nav [data-view="bays"]')

    # Shop (default): Bays shown on both desktop and mobile.
    expect(bays_desktop).to_be_visible()

    def switch_to(mode: str) -> None:
        page.click(f'[data-mode-preview="{mode}"]')
        expect(page.locator("#operating-mode-preview")).to_be_visible()
        page.click("#operating-mode-confirm")

    # Solo -> Bays hidden (desktop + mobile parity).
    switch_to("solo")
    expect(page.locator("#operating-mode-current")).to_contain_text("Solo mode")
    expect(bays_desktop).to_be_hidden()
    assert bays_mobile.get_attribute("hidden") is not None

    # Mobile Field -> Bays still hidden.
    switch_to("mobile_field")
    expect(page.locator("#operating-mode-current")).to_contain_text("Mobile Field mode")
    expect(bays_desktop).to_be_hidden()
    assert bays_mobile.get_attribute("hidden") is not None

    # Back to Shop -> Bays reappears on both.
    switch_to("shop")
    expect(page.locator("#operating-mode-current")).to_contain_text("Shop mode")
    expect(bays_desktop).to_be_visible()
    assert bays_mobile.get_attribute("hidden") is None


def test_technician_never_sees_mode_controls_and_never_calls_capabilities(
    page: Page, live_server: LiveServer, synthetic_technician: SyntheticCredentials
) -> None:
    capability_calls: list[str] = []
    page.on(
        "request",
        lambda req: capability_calls.append(req.url) if "/api/capabilities" in req.url else None,
    )

    _login(page, live_server, synthetic_technician)
    expect(page.locator("#view-my-day")).to_be_visible()

    # The System bay is reachable for a technician, but the owner-only mode
    # panel inside it must stay hidden.
    page.click('#sidebar [data-view="system"]')
    expect(page.locator("#view-system")).to_be_visible()
    expect(page.locator("#operating-mode-panel")).to_be_hidden()

    # Requirement 9: the owner-only capabilities endpoint is never called for
    # a technician session.
    page.wait_for_timeout(500)
    assert capability_calls == [], (
        f"technician unexpectedly called capabilities: {capability_calls}"
    )


def test_support_never_sees_mode_controls_and_never_calls_capabilities(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    capability_calls: list[str] = []
    page.on(
        "request",
        lambda req: capability_calls.append(req.url) if "/api/capabilities" in req.url else None,
    )

    session_factory = build_session_factory(live_server.database_url)
    support_username = f"support-mode-{synthetic_owner.user_id}"
    support_password = "support-mode-password-123"
    with session_factory() as db:
        assert (
            db.scalar(select(UserAccount).where(UserAccount.username == support_username)) is None
        )
        db.add(
            UserAccount(
                username=support_username,
                display_name="Support",
                role="support",
                password_hash=hash_password(support_password),
                is_active=True,
            )
        )
        db.commit()
        support_id = db.scalar(
            select(UserAccount.id).where(UserAccount.username == support_username)
        )

    try:
        page.goto(f"{live_server.base_url}/login")
        page.fill("#login-username", support_username)
        page.fill("#login-password", support_password)
        page.click("#login-submit")
        expect(page.locator("#view-support-directory")).to_be_visible()

        # Support has no shop; the owner-only mode panel is never surfaced.
        expect(page.locator("#operating-mode-panel")).to_be_hidden()
        page.wait_for_timeout(500)
        assert capability_calls == [], (
            f"support unexpectedly called capabilities: {capability_calls}"
        )
    finally:
        with session_factory() as db:
            row = db.get(UserAccount, support_id)
            if row is not None:
                db.delete(row)
                db.commit()


def test_stale_apply_returns_409_and_forces_a_fresh_preview(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    _login(page, live_server, synthetic_owner)
    expect(page.locator("#view-dashboard")).to_be_visible()
    page.click('#sidebar [data-view="system"]')
    expect(page.locator("#operating-mode-panel")).to_be_visible()

    # Preview Shop -> Solo (this preview's expected_current_mode is "shop").
    page.click('[data-mode-preview="solo"]')
    expect(page.locator("#operating-mode-preview")).to_be_visible()

    # Out-of-band, change the real mode to Mobile Field (simulates another
    # session/tab), making the pending Solo preview stale.
    status = page.evaluate(
        """async () => {
            const r = await fetch('/api/operating-mode/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ expected_current_mode: 'shop', proposed_mode: 'mobile_field' }),
            });
            return r.status;
        }"""
    )
    assert status == 200

    # Confirming the stale preview now conflicts -> 409 handled in-UI: the
    # preview is dropped, current mode reloaded, and a fresh preview required.
    page.click("#operating-mode-confirm")
    expect(page.locator("#operating-mode-status")).to_contain_text("changed in another session")
    expect(page.locator("#operating-mode-preview")).to_be_hidden()
    expect(page.locator("#operating-mode-current")).to_contain_text("Mobile Field mode")


def test_capabilities_fetch_failure_fails_open_to_role_based_nav(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    # Force every capabilities fetch to fail before login triggers one.
    page.route(
        "**/api/capabilities",
        lambda route: route.fulfill(
            status=503, content_type="application/json", body='{"detail":"down"}'
        ),
    )

    _login(page, live_server, synthetic_owner)
    expect(page.locator("#view-dashboard")).to_be_visible()

    # Fail open: nav falls back to role visibility, so an owner still sees
    # every owner nav item, including Bays.
    expect(page.locator('#sidebar [data-view="bays"]')).to_be_visible()
    expect(page.locator('#sidebar [data-view="technicians"]')).to_be_visible()

    page.click('#sidebar [data-view="system"]')
    expect(page.locator("#view-system")).to_be_visible()
    # No misleading mode is shown when the snapshot can't be loaded.
    expect(page.locator("#operating-mode-current")).to_contain_text("unavailable")


def test_hidden_bays_nav_does_not_change_the_backend_route(
    page: Page, live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    _login(page, live_server, synthetic_owner)
    expect(page.locator("#view-dashboard")).to_be_visible()
    page.click('#sidebar [data-view="system"]')
    expect(page.locator("#operating-mode-panel")).to_be_visible()

    # Switch to Solo, which hides the Bays nav item.
    page.click('[data-mode-preview="solo"]')
    expect(page.locator("#operating-mode-preview")).to_be_visible()
    page.click("#operating-mode-confirm")
    expect(page.locator('#sidebar [data-view="bays"]')).to_be_hidden()

    # The backend /api/bays route is still fully reachable -- the UI only
    # reshaped the default surface, it did not enforce anything (ADR-022 §4).
    status = page.evaluate(
        """async () => {
            const r = await fetch('/api/bays?page=1&page_size=10&archived=false', {
                credentials: 'same-origin',
            });
            return r.status;
        }"""
    )
    assert status == 200
