from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

import app.main as main
from app.auth import bootstrap_owner_account
from app.config import Settings
from app.db import Base, build_engine, build_session_factory


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
