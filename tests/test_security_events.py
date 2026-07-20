"""Tests for the normalized security-audit contract (Phase 1).

The inventory found four incompatible audit-event shapes and a
log_security_event whose fields varied per call site (e.g. the five
SQUARE_API_FAILED sites silently lacked request context). This verifies the
one normalized contract every structured security-log line now conforms to:
a stable event type, an actor (covering every actor kind -- user, service,
API key, background job, AI tool, anonymous), a result, a correlation id, a
timestamp, an action, and structured metadata -- and that the pre-existing
freeform-kwargs call style still works unchanged.
"""

from __future__ import annotations

import logging

from app.observability import request_id_var
from app.security_events import (
    ActorType,
    EventResult,
    SecurityEventType,
    build_security_audit_event,
    log_security_event,
)


class TestNormalizedContract:
    def test_every_event_has_the_standard_fields(self) -> None:
        event = build_security_audit_event(SecurityEventType.RECORD_WRITTEN)
        extra = event.to_log_extra()
        for key in (
            "security_event",
            "actor_type",
            "result",
            "correlation_id",
            "occurred_at",
            "action",
        ):
            assert key in extra, f"normalized event must always carry {key}"

    def test_result_defaults_are_derived_from_event_type(self) -> None:
        assert (
            build_security_audit_event(SecurityEventType.LOGIN_FAILED).result is EventResult.FAILURE
        )
        assert (
            build_security_audit_event(SecurityEventType.RATE_LIMIT_EXCEEDED).result
            is EventResult.BLOCKED
        )
        assert (
            build_security_audit_event(SecurityEventType.LOGIN_SUCCEEDED).result
            is EventResult.SUCCESS
        )

    def test_explicit_result_overrides_the_default(self) -> None:
        event = build_security_audit_event(
            SecurityEventType.RECORD_WRITTEN, result=EventResult.BLOCKED
        )
        assert event.result is EventResult.BLOCKED

    def test_correlation_id_comes_from_the_request_context(self) -> None:
        token = request_id_var.set("corr-12345")
        try:
            event = build_security_audit_event(SecurityEventType.SENSITIVE_READ)
        finally:
            request_id_var.reset(token)
        assert event.correlation_id == "corr-12345"
        # Present even when no `request` object is threaded through -- this is
        # what closes the Square/billing "no request context" gap.
        assert event.request_path is None

    def test_metadata_never_overwrites_a_standardized_field(self) -> None:
        event = build_security_audit_event(
            SecurityEventType.RECORD_WRITTEN,
            result=EventResult.SUCCESS,
            metadata={"result": "attacker-controlled", "custom": "ok"},
        )
        extra = event.to_log_extra()
        assert extra["result"] == "success"  # standardized field wins
        assert extra["custom"] == "ok"  # genuine metadata still present


class TestActorTypesAreAllRepresentable:
    def test_user_actor(self) -> None:
        event = build_security_audit_event(
            SecurityEventType.RECORD_WRITTEN,
            actor_type=ActorType.USER,
            actor_id=42,
            actor_label="owner",
        )
        assert event.to_log_extra()["actor_type"] == "user"
        assert event.to_log_extra()["actor_id"] == "42"

    def test_service_actor(self) -> None:
        event = build_security_audit_event(
            SecurityEventType.SQUARE_API_FAILED, actor_type=ActorType.SERVICE, actor_label="square"
        )
        assert event.to_log_extra()["actor_type"] == "service"

    def test_api_key_actor(self) -> None:
        event = build_security_audit_event(
            SecurityEventType.API_KEY_USED,
            actor_type=ActorType.API_KEY,
            actor_label="openai:sk-...abcd",  # a fingerprint, never the key
        )
        assert event.to_log_extra()["actor_type"] == "api_key"

    def test_background_job_actor(self) -> None:
        event = build_security_audit_event(
            SecurityEventType.RECORD_WRITTEN,
            actor_type=ActorType.BACKGROUND_JOB,
            actor_label="optimus_worker",
        )
        assert event.to_log_extra()["actor_type"] == "background_job"

    def test_ai_tool_actor(self) -> None:
        event = build_security_audit_event(
            SecurityEventType.RECORD_WRITTEN,
            actor_type=ActorType.AI_TOOL,
            actor_label="optimus_plan_executor",
        )
        assert event.to_log_extra()["actor_type"] == "ai_tool"

    def test_anonymous_is_the_default(self) -> None:
        event = build_security_audit_event(SecurityEventType.LOGIN_FAILED)
        assert event.to_log_extra()["actor_type"] == "anonymous"


class TestLogSecurityEventBackwardCompatibility:
    def test_legacy_freeform_kwargs_still_work(self, caplog) -> None:  # type: ignore[no-untyped-def]
        with caplog.at_level(logging.WARNING, logger="optimus"):
            log_security_event(
                logging.getLogger("optimus"),
                SecurityEventType.RATE_LIMIT_EXCEEDED,
                limit_key="login:203.0.113.9",
            )
        record = caplog.records[-1]
        # Unchanged human message the existing test suite asserts on.
        assert "security event: rate_limit.exceeded" in caplog.text
        # Legacy freeform field preserved as metadata.
        assert record.limit_key == "login:203.0.113.9"  # type: ignore[attr-defined]
        # Newly-guaranteed normalized fields present.
        assert record.actor_type == "anonymous"  # type: ignore[attr-defined]
        assert record.result == "blocked"  # type: ignore[attr-defined]
        assert hasattr(record, "correlation_id")

    def test_actor_context_is_emitted_when_provided(self, caplog) -> None:  # type: ignore[no-untyped-def]
        with caplog.at_level(logging.WARNING, logger="optimus"):
            log_security_event(
                logging.getLogger("optimus"),
                SecurityEventType.SQUARE_API_FAILED,
                actor_type=ActorType.USER,
                actor_id=7,
                actor_label="owner",
                operation="subscribe",
            )
        record = caplog.records[-1]
        assert record.actor_type == "user"  # type: ignore[attr-defined]
        assert record.actor_id == "7"  # type: ignore[attr-defined]
        assert record.result == "failure"  # SQUARE_API_FAILED default  # type: ignore[attr-defined]
        assert record.operation == "subscribe"  # type: ignore[attr-defined]

    def test_no_configured_secret_shaped_kwarg_is_invented_by_the_contract(self, caplog) -> None:  # type: ignore[no-untyped-def]
        """The contract adds only non-secret fields (type, result,
        correlation id, timestamp, action) -- it must never fabricate or echo
        a credential. Callers remain responsible for what they pass."""
        with caplog.at_level(logging.WARNING, logger="optimus"):
            log_security_event(logging.getLogger("optimus"), SecurityEventType.LOGIN_SUCCEEDED)
        record = caplog.records[-1]
        rendered = " ".join(f"{k}={v}" for k, v in record.__dict__.items())
        for forbidden in ("password", "secret", "token", "api_key"):
            assert forbidden not in rendered.lower()
