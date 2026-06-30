from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

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
        "estimate-form",
        "use-location",
        "access-token",
        "result",
    ):
        assert f'id="{element_id}"' in html
    assert 'fetch("/api/chat"' in javascript
    assert 'fetch("/api/estimate"' in javascript
    assert 'fetch("/health"' in javascript


def test_local_launcher_uses_fragment_token_not_query_string() -> None:
    launcher = (ROOT / "local.bat").read_text(encoding="utf-8")
    opener = (ROOT / "scripts" / "open_when_ready.ps1").read_text(encoding="utf-8")
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '-AccessToken "%OPTIMUS_TOKEN%"' in launcher
    assert "#access_token=" in opener
    assert "?access_token=" not in opener
    assert 'hash.get("access_token")' in javascript
    assert "history.replaceState" in javascript


def test_health_identifies_official_build() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "7.0.1"
    assert payload["business_name"] == "Landon Motor Works"
    assert payload["business_tagline"] == "Mobile Mechanic Intelligence"


def test_static_command_center_is_served_with_strict_headers() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Optimus Command Center" in response.text
    policy = response.headers["content-security-policy"]
    assert "default-src 'self'" in policy
    assert "'unsafe-inline'" not in policy
    css = client.get("/static/styles.css")
    manifest = client.get("/static/manifest.webmanifest")
    assert css.status_code == 200
    assert manifest.status_code == 200
