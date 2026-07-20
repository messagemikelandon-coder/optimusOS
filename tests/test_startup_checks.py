"""Tests for app/startup_checks.py -- the Phase 1 security-kernel fix for
"the server boots fine with blank/placeholder/malformed production secrets."

Mirrors the architecture lesson from the Laravel PoC (docs/architecture/adr/
ADR-018-environment-database-validation.md): a wrong or unsafe production
configuration must be a loud, immediate boot failure, never a silent
divergence discovered later. Development and test environments are
untouched by this check -- only app_env == "production" is ever gated.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.config import Settings
from app.startup_checks import (
    UnsafeProductionConfigError,
    find_unsafe_production_config,
    validate_production_config,
)


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "app_env": "production",
        "openai_api_key": "sk-" + "a" * 30,
        "optimus_owner_username": "owner",
        "optimus_owner_password": "a-genuinely-long-owner-password",
        "database_url": "postgresql+psycopg://user:pass@host:5432/db",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


class TestNonProductionEnvironmentsAreNeverGated:
    @pytest.mark.parametrize(
        "env", ["test", "local", "development", "staging-like-but-not-production"]
    )
    def test_any_secret_state_is_allowed_outside_production(self, env: str) -> None:
        settings = _settings(
            app_env=env,
            openai_api_key="",
            optimus_owner_username="",
            optimus_owner_password="",
            database_url="sqlite:///:memory:",
        )
        assert find_unsafe_production_config(settings) == []
        validate_production_config(settings)  # must not raise


class TestProductionConfigIsValidated:
    def test_valid_production_config_passes(self) -> None:
        settings = _settings()
        assert find_unsafe_production_config(settings) == []
        validate_production_config(settings)  # must not raise

    def test_blank_openai_key_fails(self) -> None:
        settings = _settings(openai_api_key="")
        problems = find_unsafe_production_config(settings)
        assert any("OPENAI_API_KEY" in p for p in problems)
        with pytest.raises(UnsafeProductionConfigError):
            validate_production_config(settings)

    def test_placeholder_openai_key_fails(self) -> None:
        settings = _settings(openai_api_key="replace_me")
        assert any("OPENAI_API_KEY" in p for p in find_unsafe_production_config(settings))

    def test_blank_owner_username_fails(self) -> None:
        settings = _settings(optimus_owner_username="")
        assert any("OPTIMUS_OWNER_USERNAME" in p for p in find_unsafe_production_config(settings))

    def test_blank_owner_password_fails(self) -> None:
        settings = _settings(optimus_owner_password="")
        assert any("OPTIMUS_OWNER_PASSWORD" in p for p in find_unsafe_production_config(settings))

    def test_placeholder_owner_password_fails(self) -> None:
        settings = _settings(optimus_owner_password="replace_with_a_long_owner_password")
        assert any("OPTIMUS_OWNER_PASSWORD" in p for p in find_unsafe_production_config(settings))

    def test_short_owner_password_fails(self) -> None:
        settings = _settings(optimus_owner_password="short12345")  # 10 chars, below the 12 minimum
        problems = find_unsafe_production_config(settings)
        assert any("at least 12 characters" in p for p in problems)

    def test_sqlite_database_url_fails_in_production(self) -> None:
        settings = _settings(database_url="sqlite:///:memory:")
        assert any("DATABASE_URL" in p for p in find_unsafe_production_config(settings))


class TestErrorNeverLeaksSecretValues:
    def test_raised_error_does_not_contain_the_configured_secret_values(self) -> None:
        secret_marker = "sk-UNIQUE-CANARY-VALUE-should-never-leak"
        settings = _settings(openai_api_key=secret_marker, optimus_owner_password="short")

        with pytest.raises(UnsafeProductionConfigError) as exc_info:
            validate_production_config(settings)

        assert secret_marker not in str(exc_info.value)
        assert "short" not in str(exc_info.value)


class TestWiredIntoRealApplicationStartup:
    """Proves the check actually gates real app boot (importing app.main,
    which is what uvicorn does to start the server), not just that the
    function works in isolation. Each subprocess runs with cwd set to an
    empty tmp dir so the repo's own authoritative `.env` file (which
    Settings.settings_customise_sources ranks above OS env vars) is not
    read -- config comes deterministically from the injected env vars plus
    Settings' own field defaults, exactly as it would in a container that
    ships no `.env`."""

    def test_importing_app_main_fails_closed_with_unsafe_production_env(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        env = {
            "APP_ENV": "production",
            "OPENAI_API_KEY": "",
            "OPTIMUS_OWNER_USERNAME": "",
            "OPTIMUS_OWNER_PASSWORD": "",
            "DATABASE_URL": "postgresql+psycopg://x:x@x:5432/x",
            "PATH": "/usr/bin:/bin",
        }
        result = subprocess.run(
            [sys.executable, "-c", "import app.main"],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode != 0
        assert (
            "Refusing to start" in result.stderr or "UnsafeProductionConfigError" in result.stderr
        )

    def test_importing_app_main_succeeds_with_safe_explicit_config(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Development and production remain usable when configured
        explicitly and safely -- the guard blocks only genuinely unsafe
        production config, never a correctly-configured server."""
        env = {
            "APP_ENV": "production",
            "OPENAI_API_KEY": "sk-" + "a" * 30,
            "OPTIMUS_OWNER_USERNAME": "owner",
            "OPTIMUS_OWNER_PASSWORD": "a-genuinely-long-owner-password",
            "DATABASE_URL": "postgresql+psycopg://x:x@x:5432/x",
            "PATH": "/usr/bin:/bin",
        }
        result = subprocess.run(
            [sys.executable, "-c", "import app.main"],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
