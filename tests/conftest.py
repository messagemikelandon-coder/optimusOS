from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

import app.config as config

# This block must run before ANY `from app.* import ...` below, and its
# ordering is load-bearing -- hence the E402 suppressions on the app imports
# that follow.
#
# Importing app.main resolves a module-level Settings() at import time (for
# configure_structured_logging(...) and, since Phase 1's security-kernel
# work, validate_production_config(...)). Settings.settings_customise_sources()
# deliberately ranks the project's .env file ABOVE real OS environment
# variables ("this is a local desktop application... .env is deliberately
# authoritative" -- see app/config.py), so a plain os.environ["APP_ENV"]
# override cannot win here the way it could for an ordinary 12-factor app:
# it would still lose to whatever a real local .env contains, or -- with no
# .env file at all, as in a fresh CI checkout -- Settings falls back to its
# own field default of app_env="production" with blank secrets, which is
# exactly the unsafe combination validate_production_config() now rejects,
# aborting the whole test run.
#
# Replacing config.get_settings with a fixed safe-test-config accessor is the
# identity-preserving fix: it must happen before app.db/app.auth/app.main are
# imported, so every module that does `from app.config import get_settings`
# (app.db's Depends(get_settings), app.main's SettingsDep, and the test
# files' own `from app.db import get_settings` used as a dependency_overrides
# key) all bind to this SAME object. Doing the swap after those imports would
# leave FastAPI's Depends and the tests' overrides pointing at two different
# get_settings objects, silently breaking dependency_overrides.
config.get_settings.cache_clear()
_module_level_test_settings = config.Settings(
    app_env="test",
    openai_api_key="test-key",
    optimus_owner_username="owner",
    optimus_owner_password="owner-password-123",
    database_url="sqlite+pysqlite:///:memory:",
)
config.get_settings = lambda: _module_level_test_settings  # type: ignore[assignment]

import app.main as main  # noqa: E402
from app.auth import bootstrap_owner_account  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import Base, build_engine, build_session_factory  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiter_singletons() -> None:
    """`main.py`'s rate limiters are process-wide, lazily-constructed
    singletons (by design, so a real deployment shares one limiter across
    requests) -- without a reset, their in-process fallback state
    accumulates across every test in a single pytest run, since nearly
    every test authenticates via the same fake client host from
    `request_for()`. Without this fixture, tests unrelated to rate
    limiting can start failing with a real 429 purely because enough
    *other* tests logged in earlier in the same process. Resetting to
    None forces a fresh limiter (and empty fallback event history) per
    test -- this only affects test isolation, not production behavior,
    since a real process never resets these between requests either."""
    main._rate_limiter = None
    main._rate_limiter_redis_url = None
    main._login_rate_limiter = None
    main._login_rate_limiter_redis_url = None
    main._signup_rate_limiter = None
    main._signup_rate_limiter_redis_url = None
    main._email_verification_resend_rate_limiter = None
    main._email_verification_resend_rate_limiter_redis_url = None
    main._email_verification_rate_limiter = None
    main._email_verification_rate_limiter_redis_url = None
    # The password-reset and invitation-acceptance limiters were previously
    # omitted here; reset all seven so no limiter's in-process fallback state
    # leaks across tests (see tests/test_rate_limit_endpoints.py, which
    # deliberately drives each limiter to its 429 threshold).
    main._password_reset_rate_limiter = None
    main._password_reset_rate_limiter_redis_url = None
    main._invitation_acceptance_rate_limiter = None
    main._invitation_acceptance_rate_limiter_redis_url = None


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        openai_api_key="test-key",
        database_url="sqlite+pysqlite:///:memory:",
        # Keep unit tests hermetic and make every Redis-backed limiter take
        # its documented in-process fallback immediately. Real Redis
        # behavior has dedicated tests that connect to 127.0.0.1:6379.
        redis_url=("redis://127.0.0.1:1/0?socket_connect_timeout=0.1&socket_timeout=0.1"),
        frontend_origin="http://127.0.0.1:5173",
        labor_rate=100,
        mobile_service_fee=25,
        shop_supplies_percent=5,
        parts_tax_rate=8.5,
        optimus_owner_username="owner",
        optimus_owner_password="owner-password-123",
        # Force a hermetic default regardless of what a real local .env might
        # contain (mirrors the openai_api_key override above) -- individual
        # Square tests opt back in explicitly via configure_square(settings).
        square_access_token="",
        square_location_id="",
        square_environment="sandbox",
    )


@pytest.fixture
def db_session(settings: Settings) -> Generator[Session, None, None]:
    engine = build_engine(settings.database_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = build_session_factory(settings.database_url)()
    try:
        bootstrap_owner_account(settings=settings, db=session)
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
