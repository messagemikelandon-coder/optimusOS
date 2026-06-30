from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        openai_api_key="test-key",
        labor_rate=100,
        mobile_service_fee=25,
        shop_supplies_percent=5,
        parts_tax_rate=8.5,
    )
