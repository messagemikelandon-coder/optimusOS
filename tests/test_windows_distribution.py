from __future__ import annotations

from pathlib import Path

from scripts.validate_runtime import is_missing_or_placeholder

ROOT = Path(__file__).resolve().parents[1]


def test_windows_entrypoints_are_packaged() -> None:
    expected = (
        "WINDOWS_SETUP.bat",
        "local.bat",
        "RUN_OPTIMUS_LOCAL.bat",
        "CHECK_OPTIMUS.bat",
        "WINDOWS_SETUP.md",
        "scripts/windows_setup.ps1",
        "scripts/open_when_ready.ps1",
        "scripts/validate_runtime.py",
        "DIAGNOSE_ESTIMATOR.bat",
        "scripts/diagnose_estimator.py",
    )
    for relative_path in expected:
        assert (ROOT / relative_path).is_file(), relative_path


def test_local_launcher_is_loopback_only() -> None:
    launcher = (ROOT / "local.bat").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in launcher
    assert "--host 0.0.0.0" not in launcher
    assert "validate_runtime.py" in launcher
    assert "open_when_ready.ps1" in launcher


def test_windows_setup_generates_token_and_uses_venv() -> None:
    setup = (ROOT / "scripts/windows_setup.ps1").read_text(encoding="utf-8")
    assert '"-m", "venv"' in setup
    assert "OPENAI_API_KEY" in setup
    assert "OPTIMUS_OWNER_USERNAME" in setup
    assert "OPTIMUS_OWNER_PASSWORD" in setup
    assert "AUTONOMY_MODE" in setup


def test_browser_uses_same_origin_cookie_auth_flow() -> None:
    javascript = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert 'credentials: "same-origin"' in javascript
    assert "/api/auth/login" in javascript
    assert "/api/auth/logout" in javascript


def test_placeholder_detection() -> None:
    assert is_missing_or_placeholder("")
    assert is_missing_or_placeholder("replace_me")
    assert is_missing_or_placeholder(" replace_with_a_long_random_token ")
    assert not is_missing_or_placeholder("sk-proj-realisticvalue")


def test_openai_recovery_entrypoints_are_packaged() -> None:
    expected = (
        "RESET_OPENAI_KEY.bat",
        "DIAGNOSE_OPENAI.bat",
        "scripts/reset_openai_key.ps1",
        "scripts/diagnose_openai_config.py",
        "app/openai_key_info.py",
    )
    for relative_path in expected:
        assert (ROOT / relative_path).is_file(), relative_path
