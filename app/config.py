from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openai_api_key: str = Field(default="", repr=False)
    openai_model: str = "gpt-5.5"
    openai_estimator_model: str = ""
    openai_fallback_model: str = "gpt-4.1-mini"
    web_search_context_size: Literal["low", "medium", "high"] = "medium"
    estimator_reasoning_effort: Literal["low", "medium", "high"] = "low"

    business_name: str = "Landon Motor Works"
    business_tagline: str = "Mobile Mechanic Intelligence"

    labor_rate: float = Field(default=100.0, ge=0, le=1000)
    mobile_service_fee: float = Field(default=0.0, ge=0, le=10_000)
    shop_supplies_percent: float = Field(default=0.0, ge=0, le=25)
    parts_tax_rate: float = Field(default=0.0, ge=0, le=20)

    http_timeout_seconds: float = Field(default=20.0, ge=2, le=120)
    openai_timeout_seconds: float = Field(default=180.0, ge=10, le=600)
    openai_max_retries: int = Field(default=2, ge=0, le=5)
    max_job_text_length: int = Field(default=500, ge=20, le=5000)
    max_chat_text_length: int = Field(default=12_000, ge=100, le=50_000)
    max_web_results: int = Field(default=20, ge=3, le=100)
    context_max_entries_per_scope: int = Field(default=24, ge=1, le=200)
    context_max_value_chars: int = Field(default=4000, ge=100, le=20_000)
    context_stale_after_hours: int = Field(default=168, ge=1, le=8760)
    customers_default_page_size: int = Field(default=20, ge=1, le=100)
    customers_max_page_size: int = Field(default=100, ge=1, le=200)
    vehicles_default_page_size: int = Field(default=20, ge=1, le=100)
    vehicles_max_page_size: int = Field(default=100, ge=1, le=200)
    work_orders_default_page_size: int = Field(default=20, ge=1, le=100)
    work_orders_max_page_size: int = Field(default=100, ge=1, le=200)
    app_env: str = "production"
    database_url: str = Field(
        default="postgresql+psycopg://optimus:optimus_local@postgres:5432/optimus_os",
        repr=False,
    )
    redis_url: str = Field(default="redis://redis:6379/0", repr=False)
    max_estimates_per_minute: int = Field(default=20, ge=1, le=240)
    log_level: str = "INFO"
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    frontend_origin: str = "http://127.0.0.1:5173"
    session_cookie_name: str = "optimus_session"
    optimus_owner_username: str = Field(default="", repr=False)
    optimus_owner_password: str = Field(default="", repr=False)

    autonomy_mode: Literal["owner_full_control", "guarded"] = "owner_full_control"
    direct_owner_chat_default: bool = True
    agent_delegation_enabled: bool = True
    max_agent_consultations: int = Field(default=2, ge=0, le=8)
    allow_public_https_parts_links: bool = True

    parts_retailer_hosts: Annotated[tuple[str, ...], NoDecode] = (
        "autozone.com",
        "www.autozone.com",
        "oreillyauto.com",
        "www.oreillyauto.com",
        "napaonline.com",
        "www.napaonline.com",
        "shop.advanceautoparts.com",
        "advanceautoparts.com",
        "www.advanceautoparts.com",
        "rockauto.com",
        "www.rockauto.com",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del settings_cls
        # This is a local desktop application. The project .env is deliberately
        # authoritative so an old Windows OPENAI_API_KEY cannot silently replace it.
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    @field_validator("parts_retailer_hosts", mode="before")
    @classmethod
    def parse_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip().lower() for part in value.split(",") if part.strip())
        return value

    @field_validator("openai_api_key")
    @classmethod
    def strip_key(cls, value: str) -> str:
        return value.strip()

    @field_validator("openai_model", "openai_estimator_model", "openai_fallback_model")
    @classmethod
    def normalize_model_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            return ""
        # Model ids should not contain spaces. Normalize common .env mistakes such as
        # "gpt-4.1 mini" to "gpt-4.1-mini" so live deployments continue to work.
        return re.sub(r"\s+", "-", cleaned)

    @field_validator(
        "optimus_owner_username",
        "optimus_owner_password",
        "session_cookie_name",
        mode="before",
    )
    @classmethod
    def strip_sensitive_values(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @property
    def estimator_model(self) -> str:
        return self.openai_estimator_model.strip() or self.openai_model.strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
