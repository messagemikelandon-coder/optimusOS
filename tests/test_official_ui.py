from __future__ import annotations

from pathlib import Path

import anyio
from starlette.requests import Request
from starlette.responses import FileResponse

from app.main import STATIC_DIR, get_settings, health, index, security_headers

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_official_landon_motor_works_interface_is_packaged() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "Landon Motor Works" in html
    assert "Optimus Command Center" in html
    assert "mechanic-stage" in html
    assert "rotor-assembly" in html
    assert "diagnostic-tablet" in html
    assert "tilt-surface" in css
    assert (STATIC / "logo-mark.svg").is_file()
    assert (STATIC / "favicon.svg").is_file()
    assert (STATIC / "manifest.webmanifest").is_file()


def test_ui_preserves_connected_workflows() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    for element_id in (
        "chat-form",
        "chat-message",
        "customer-form",
        "customers-search",
        "customers-list",
        "customer-detail",
        "customer-vehicles-list",
        "vehicle-form",
        "vehicles-search",
        "vehicles-customer-filter",
        "vehicles-list",
        "vehicle-detail",
        "estimate-form",
        "estimate-selected-customer",
        "estimate-selected-vehicle",
        "approval-public-root",
        "use-location",
        "login-form",
        "login-username",
        "login-password",
        "result",
    ):
        assert f'id="{element_id}"' in html
    assert 'apiFetch("/api/auth/login"' in javascript
    assert 'apiFetch("/api/auth/me"' in javascript
    assert "/api/customers" in javascript
    assert "/api/vehicles" in javascript
    assert "/api/context/vehicles/selected-vehicle?scope=session" in javascript
    assert "/api/context/estimates/selected-estimate?scope=session" in javascript
    assert 'apiFetch("/api/chat"' in javascript
    assert "/api/estimates" in javascript
    assert "/api/estimate-approval/view" in javascript
    assert 'apiFetch("/health"' in javascript


def test_local_launcher_opens_login_url_without_credentials_in_fragment() -> None:
    launcher = (ROOT / "local.bat").read_text(encoding="utf-8")
    opener = (ROOT / "scripts" / "open_when_ready.ps1").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "Login: http://127.0.0.1:8000/login" in launcher
    assert "Start-Process $Url" in opener
    assert "access_token" not in opener
    assert "optimus_access_token" not in javascript
    assert 'credentials: "same-origin"' in javascript


def test_playwright_audit_supports_safe_authenticated_smoke_mode() -> None:
    audit_script = (ROOT / "scripts" / "ui_connection_audit_playwright.js").read_text(
        encoding="utf-8"
    )
    assert "OPTIMUS_AUDIT_SKIP_DOCKER" in audit_script
    assert "OPTIMUS_AUDIT_SKIP_BILLABLE" in audit_script
    assert '"/api/auth/me"' in audit_script
    assert '"/api/location/resolve"' in audit_script
    assert '"/api/vehicles"' in audit_script
    assert '"/api/estimates"' in audit_script
    assert '"/send-for-approval"' in audit_script


def test_health_identifies_official_build() -> None:
    payload = anyio.run(health, get_settings())
    assert payload["version"] == "7.0.1"
    assert payload["business_name"] == "Landon Motor Works"
    assert payload["business_tagline"] == "Mobile Mechanic Intelligence"


def test_static_command_center_is_served_with_strict_headers() -> None:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "scheme": "http",
            "method": "GET",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
    )

    async def call_next(_: Request) -> FileResponse:
        return await index()

    response = anyio.run(security_headers, request, call_next)
    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "'unsafe-inline'" not in policy
    assert (STATIC_DIR / "styles.css").is_file()
    assert (STATIC_DIR / "manifest.webmanifest").is_file()
