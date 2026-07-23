from __future__ import annotations

import re
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
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
    # Optional, opt-in $/1K-token pricing for cost logging (Phase 6 Part H).
    # Unset (None) by default -- OpenAI's published prices change over time
    # and this app has no live pricing API, so guessing a number here would
    # be a fabricated cost estimate, not a real one. When left unset, usage
    # is still logged (real, verifiable token counts) but no dollar estimate
    # is computed; the owner can fill these in from OpenAI's current pricing
    # page to turn on estimated-cost logging.
    openai_estimator_model_input_cost_per_1k: float | None = Field(default=None, ge=0)
    openai_estimator_model_output_cost_per_1k: float | None = Field(default=None, ge=0)
    openai_fallback_model_input_cost_per_1k: float | None = Field(default=None, ge=0)
    openai_fallback_model_output_cost_per_1k: float | None = Field(default=None, ge=0)
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
    invoices_default_page_size: int = Field(default=20, ge=1, le=100)
    invoices_max_page_size: int = Field(default=100, ge=1, le=200)
    notifications_default_page_size: int = Field(default=20, ge=1, le=100)
    notifications_max_page_size: int = Field(default=100, ge=1, le=200)
    invoice_due_days_default: int = Field(default=30, ge=1, le=180)
    app_env: str = "production"
    database_url: str = Field(
        default="postgresql+psycopg://optimus:optimus_local@postgres:5432/optimus_os",
        repr=False,
    )
    redis_url: str = Field(default="redis://redis:6379/0", repr=False)
    max_estimates_per_minute: int = Field(default=20, ge=1, le=240)
    max_login_attempts_per_minute: int = Field(default=10, ge=1, le=240)
    max_signup_attempts_per_minute: int = Field(default=5, ge=1, le=240)
    max_email_verification_attempts_per_minute: int = Field(default=20, ge=1, le=240)
    max_email_verification_resend_attempts_per_hour: int = Field(default=5, ge=1, le=240)
    email_verification_token_ttl_hours: int = Field(default=24, ge=1, le=168)
    password_reset_token_ttl_minutes: int = Field(default=30, ge=5, le=1440)
    max_password_reset_attempts_per_hour: int = Field(default=5, ge=1, le=240)
    max_invitation_acceptance_attempts_per_hour: int = Field(default=20, ge=1, le=240)
    account_lockout_failure_threshold: int = Field(default=5, ge=3, le=50)
    account_lockout_minutes: int = Field(default=15, ge=1, le=1440)
    shop_invitation_token_ttl_hours: int = Field(default=72, ge=1, le=720)
    log_level: str = "INFO"
    # Phase 2A: read-only host-disk / Docker-storage observability thresholds.
    # `disk_monitor_path` is the filesystem the /api/operations/storage endpoint
    # samples via shutil.disk_usage from inside the app process. Default "/" is
    # the container root; point it at a mounted data-volume path if one is
    # mounted into this container. NOTE: the Postgres data volume is not mounted
    # into the backend container by default, so from inside the backend this
    # sees the container filesystem, not the Postgres volume host disk -- see
    # docs/context/MONITORING.md for that operational limitation.
    # used_percent >= critical => "critical"; >= warning => "warning".
    # `disk_monitor_path` is used internally to choose which filesystem to
    # sample; it is NEVER returned in a response or written to a log. The
    # non-sensitive `storage_target_label` is exposed instead, so a sensitive
    # host path can't leak through the support endpoint.
    disk_monitor_path: str = "/"
    storage_target_label: str = "application_filesystem"
    disk_warning_percent: float = Field(default=80.0, ge=0, le=100)
    disk_critical_percent: float = Field(default=90.0, ge=0, le=100)
    # Bounded collection: reuse a snapshot for this TTL (one Docker subprocess
    # per window at most), and throttle repeated reliability warnings during a
    # sustained elevated state to at most once per cooldown. The support
    # endpoint is additionally rate-limited per client.
    storage_snapshot_ttl_seconds: int = Field(default=30, ge=1, le=3600)
    storage_warning_cooldown_seconds: int = Field(default=300, ge=0, le=86_400)
    max_operations_storage_requests_per_minute: int = Field(default=30, ge=1, le=240)
    # Phase 2B: bounded runtime observability for GET /api/operations/summary.
    # The background worker refreshes `worker_heartbeat_redis_key` every
    # `worker_heartbeat_interval_seconds` with a `worker_heartbeat_ttl_seconds`
    # expiry (validated >= 2x interval so a live worker's key survives across
    # beats even with dependency-probe latency in the loop). The value stored is
    # a single epoch second -- never job/customer
    # data. `worker_queue_redis_key` is EMPTY by default: there is no application
    # work queue today (ADR-014 records a future queue would be Postgres
    # SKIP LOCKED, not Redis), so the summary reports the queue as
    # "not_configured" and never touches Redis for it unless an operator sets a
    # real Redis list key here. The runtime snapshot is served from a TTL cache
    # with single-flight collection (one probe/read pass per window at most),
    # the degraded reliability warning is throttled by cooldown, and the
    # endpoint is additionally rate-limited per client.
    worker_heartbeat_redis_key: str = "optimus:worker:heartbeat"
    worker_heartbeat_interval_seconds: int = Field(default=30, ge=5, le=3600)
    worker_heartbeat_ttl_seconds: int = Field(default=150, ge=10, le=86_400)
    worker_queue_redis_key: str = ""
    runtime_snapshot_ttl_seconds: int = Field(default=15, ge=1, le=3600)
    dependency_probe_timeout_seconds: float = Field(default=1.0, ge=0.1, le=10.0)
    runtime_warning_cooldown_seconds: int = Field(default=300, ge=0, le=86_400)
    max_operations_summary_requests_per_minute: int = Field(default=30, ge=1, le=240)
    # Vehicle-first intake: standalone VIN decode triggers one outbound NHTSA
    # vPIC lookup, so it is throttled per client to bound the outbound-call rate.
    max_vin_decode_requests_per_minute: int = Field(default=20, ge=1, le=240)
    # Recommendation-only AI job-input proposals trigger one outbound (paid) LLM
    # call per request, so they are throttled per client to bound cost/abuse.
    max_job_proposal_requests_per_minute: int = Field(default=10, ge=1, le=120)
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    frontend_origin: str = "http://127.0.0.1:5173"
    session_cookie_name: str = "optimus_session"
    optimus_owner_username: str = Field(default="", repr=False)
    optimus_owner_password: str = Field(default="", repr=False)
    # /goal Phase 8: a platform-side, read-only support operator account.
    # Never self-service, never granted by a shop owner -- provisioned the
    # same way the first owner account is, via app/bootstrap_support.py.
    optimus_support_username: str = Field(default="", repr=False)
    optimus_support_password: str = Field(default="", repr=False)

    square_access_token: str = Field(default="", repr=False)
    square_environment: Literal["sandbox", "production"] = "sandbox"
    square_location_id: str = ""
    square_timeout_seconds: float = Field(default=20.0, ge=2, le=120)

    # /goal Phase 7: Square Subscriptions plan-variation ids for OptimusOS's
    # own shop-subscription tiers (billing the shop, distinct from the
    # customer-invoice integration above). Each must be created once in the
    # Square Catalog (sandbox) before that tier can be subscribed to; a blank
    # value means that tier is not yet billable and `subscribe()` rejects it
    # with a clear error rather than calling Square with an empty id.
    square_solo_plan_variation_id: str = ""
    square_team_plan_variation_id: str = ""
    square_shop_plan_variation_id: str = ""

    autonomy_mode: Literal["owner_full_control", "guarded"] = "owner_full_control"
    direct_owner_chat_default: bool = True
    agent_delegation_enabled: bool = True
    max_agent_consultations: int = Field(default=2, ge=0, le=8)
    allow_public_https_parts_links: bool = True

    # Synthetic test-account provisioning (Phase 6 Part B). Off by default in
    # every environment, including local dev and CI, unless both this flag and
    # app_env are explicitly overridden -- see app/test_support_store.py.
    optimus_test_account_provisioning: bool = False

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

    @field_validator(
        "openai_estimator_model_input_cost_per_1k",
        "openai_estimator_model_output_cost_per_1k",
        "openai_fallback_model_input_cost_per_1k",
        "openai_fallback_model_output_cost_per_1k",
        mode="before",
    )
    @classmethod
    def blank_cost_is_unconfigured(cls, value: object) -> object:
        # .env.example ships these keys present but blank (the documented
        # "not configured yet" state) -- an empty string must mean None, not
        # a float-parsing error, or a fresh checkout with these keys still
        # blank would fail to start at all. These are this class's first
        # `X | None`-typed numeric fields; any future Optional[int]/
        # Optional[float] setting needs the same before-validator pattern,
        # or a blank .env value for it will crash the app at startup the
        # same way this one did before this fix.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("openai_api_key")
    @classmethod
    def strip_key(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _validate_disk_thresholds(self) -> Settings:
        # A warning threshold above the critical threshold would silently
        # swallow the whole "warning" band (critical is checked first), so
        # reject the misconfiguration at startup rather than degrade quietly.
        if self.disk_warning_percent > self.disk_critical_percent:
            raise ValueError(
                "DISK_WARNING_PERCENT must be less than or equal to DISK_CRITICAL_PERCENT"
            )
        return self

    @model_validator(mode="after")
    def _validate_worker_heartbeat(self) -> Settings:
        # The heartbeat key's TTL must comfortably outlast the write interval,
        # or a healthy worker's key expires between beats and the summary reports
        # a live worker as "missing" (a false degraded signal). The real gap
        # between two writes is `interval` PLUS the worker loop's per-cycle
        # overhead (two TCP dependency probes + the write), so `ttl == interval`
        # is not enough. Requiring `ttl >= 2 * interval` guarantees no lapse for
        # every accepted config: the healthy gap (interval + a few seconds of
        # probe latency) is strictly below 2*interval whenever interval exceeds
        # that overhead, which holds across the allowed interval range (>= 5s).
        if self.worker_heartbeat_ttl_seconds < 2 * self.worker_heartbeat_interval_seconds:
            raise ValueError(
                "WORKER_HEARTBEAT_TTL_SECONDS must be at least twice "
                "WORKER_HEARTBEAT_INTERVAL_SECONDS (so a healthy worker's key "
                "survives across beats, absorbing dependency-probe latency)"
            )
        return self

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
        "optimus_support_username",
        "optimus_support_password",
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

    @property
    def square_configured(self) -> bool:
        # Sandbox-only phase: production is structurally unreachable until a
        # separate, explicitly approved go-live change relaxes this gate.
        return (
            bool(self.square_access_token and self.square_location_id)
            and self.square_environment == "sandbox"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
