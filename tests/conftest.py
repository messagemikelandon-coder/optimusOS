from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from app.auth import bootstrap_owner_account
from app.config import Settings
from app.db import Base, build_engine, build_session_factory


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        openai_api_key="test-key",
        database_url="sqlite+pysqlite:///:memory:",
        frontend_origin="http://127.0.0.1:5173",
        labor_rate=100,
        mobile_service_fee=25,
        shop_supplies_percent=5,
        parts_tax_rate=8.5,
        optimus_owner_username="owner",
        optimus_owner_password="owner-password-123",
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
