"""Fail-secure startup validation for production configuration.

Ported from the existing `scripts/validate_runtime.py`/`scripts/check_config.py`
checks -- this module makes that same logic gate real application boot,
not just a manual CLI diagnostic an operator has to remember to run.

Reports only setting *names* that are missing or invalid, never a secret
value or any fragment of one. Development and test environments (any
`app_env` other than ``"production"``) are never affected by this check,
regardless of what secrets are or aren't configured -- this mirrors the
existing `app_env != "production"` boundary already used by
`app/test_support_store.py` for gating synthetic-account provisioning,
rather than introducing a new environment concept.
"""

from __future__ import annotations

from app.config import Settings

_PLACEHOLDERS = {
    "replace_me",
    "your_actual_openai_api_key",
    "replace_with_a_long_random_token",
    "replace_with_a_long_owner_password",
}

_MIN_OWNER_PASSWORD_LENGTH = 12


class UnsafeProductionConfigError(RuntimeError):
    """Raised when ``app_env == "production"`` but required secrets are
    blank, a placeholder, malformed, or missing."""


def _is_missing_or_placeholder(value: str) -> bool:
    normalized = value.strip()
    return not normalized or normalized.lower() in _PLACEHOLDERS


def find_unsafe_production_config(settings: Settings) -> list[str]:
    """Returns setting *names* (never values) that fail production safety
    requirements. An empty list means the configuration is safe -- this is
    always the case when ``app_env != "production"``."""
    if settings.app_env != "production":
        return []

    problems: list[str] = []

    if _is_missing_or_placeholder(settings.openai_api_key):
        problems.append("OPENAI_API_KEY is missing or a placeholder value")

    if not settings.optimus_owner_username.strip():
        problems.append("OPTIMUS_OWNER_USERNAME is missing")

    if _is_missing_or_placeholder(settings.optimus_owner_password):
        problems.append("OPTIMUS_OWNER_PASSWORD is missing or a placeholder value")
    elif len(settings.optimus_owner_password) < _MIN_OWNER_PASSWORD_LENGTH:
        problems.append(
            f"OPTIMUS_OWNER_PASSWORD must be at least {_MIN_OWNER_PASSWORD_LENGTH} characters"
        )

    if settings.database_url.startswith("sqlite"):
        problems.append("DATABASE_URL must not be sqlite in production")

    return problems


def validate_production_config(settings: Settings) -> None:
    """Raises :class:`UnsafeProductionConfigError` if this is a production
    environment with unsafe configuration. A no-op for every other
    ``app_env`` value, so local development and the test suite remain
    fully usable with whatever explicit configuration they already have.
    """
    problems = find_unsafe_production_config(settings)
    if problems:
        raise UnsafeProductionConfigError(
            "Refusing to start: unsafe production configuration ("
            + "; ".join(problems)
            + "). Set real values via environment variables. This message "
            "intentionally never includes the configured values themselves."
        )
