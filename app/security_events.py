from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from fastapi import Request

from app.observability import request_id_var

_EVENT_FIELD = "security_event"


class SecurityEventType(StrEnum):
    """The security-event taxonomy. Scoped to events this codebase can
    actually emit; new categories are added here (never invented ad hoc at a
    call site) so a log aggregator / Sentinel can alert on a stable,
    enumerable set."""

    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    SIGNUP_SUCCEEDED = "auth.signup_succeeded"
    SIGNUP_FAILED = "auth.signup_failed"
    EMAIL_VERIFICATION_REQUESTED = "auth.email_verification_requested"
    EMAIL_VERIFICATION_FAILED = "auth.email_verification_failed"
    EMAIL_VERIFIED = "auth.email_verified"
    PASSWORD_CHANGED = "auth.password_changed"
    PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"
    PASSWORD_RESET_COMPLETED = "auth.password_reset_completed"
    SESSION_REVOKED = "auth.session_revoked"
    INVITATION_CREATED = "auth.invitation_created"
    INVITATION_ACCEPTED = "auth.invitation_accepted"
    INVITATION_REVOKED = "auth.invitation_revoked"
    ACCOUNT_STATUS_CHANGED = "auth.account_status_changed"
    RATE_LIMIT_EXCEEDED = "rate_limit.exceeded"
    SQUARE_API_FAILED = "square.api_failed"
    SUPPORT_DIRECTORY_VIEWED = "support.directory_viewed"
    SUPPORT_IMPERSONATION_STARTED = "support.impersonation_started"
    SUPPORT_IMPERSONATION_ENDED = "support.impersonation_ended"
    # Phase 1 security-kernel additions -- categories the inventory identified
    # as needed for consistent coverage of sensitive activity, ahead of
    # Sentinel ingestion (see docs/architecture/PHASE1-SECURITY-KERNEL-PLAN.md).
    # Not yet emitted at any call site; added here so future emitters draw
    # from one enumerable taxonomy rather than inventing free-text types.
    ACCESS_DENIED = "authz.access_denied"
    SENSITIVE_READ = "data.sensitive_read"
    RECORD_WRITTEN = "data.record_written"
    APPROVAL_GRANTED = "approval.granted"
    API_KEY_USED = "api_key.used"
    SUPPORT_ACCESS = "support.access"
    SECURITY_SETTING_CHANGED = "security.setting_changed"
    # ADR-022 capability observe pilot: emitted once per gated request by
    # app/capability_gate.py. In the observe-only pilot this never changes a
    # request's outcome -- it records what a future ENFORCE mode *would* have
    # decided (would_allow/would_deny), so operators can validate the
    # capability matrix against real traffic before any enforcement is
    # activated. A separate category (not ACCESS_DENIED) precisely because an
    # observation is not a denial.
    CAPABILITY_OBSERVED = "authz.capability_observed"


class ActorType(StrEnum):
    """Who (or what) performed the action. A normalized event always names an
    actor type, so a background job or AI tool acting on data is never
    indistinguishable from an anonymous request in the audit stream."""

    USER = "user"
    SERVICE = "service"
    API_KEY = "api_key"
    BACKGROUND_JOB = "background_job"
    AI_TOOL = "ai_tool"
    ANONYMOUS = "anonymous"


class EventResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED = "blocked"


# Event types whose result is inherently a failure/blocked outcome, so callers
# don't have to pass result= for the obvious cases (and can't get it wrong).
_FAILURE_EVENTS = frozenset(
    {
        SecurityEventType.LOGIN_FAILED,
        SecurityEventType.SIGNUP_FAILED,
        SecurityEventType.EMAIL_VERIFICATION_FAILED,
        SecurityEventType.SQUARE_API_FAILED,
    }
)
_BLOCKED_EVENTS = frozenset(
    {
        SecurityEventType.RATE_LIMIT_EXCEEDED,
        SecurityEventType.ACCESS_DENIED,
    }
)


def _default_result(event_type: SecurityEventType) -> EventResult:
    if event_type in _FAILURE_EVENTS:
        return EventResult.FAILURE
    if event_type in _BLOCKED_EVENTS:
        return EventResult.BLOCKED
    return EventResult.SUCCESS


@dataclass(frozen=True)
class SecurityAuditEvent:
    """The single normalized security-audit contract every structured
    security-log line conforms to. It gives the four previously-incompatible
    ad-hoc shapes one field vocabulary -- actor, tenant, request, action,
    resource, result, timestamp, correlation id, and metadata -- suitable
    for direct Sentinel ingestion. `metadata` carries any additional,
    event-specific fields (the former freeform **kwargs) without polluting
    the standardized top level.

    Never place a secret (password, token, API key, raw session cookie) in
    any field; like the rest of the codebase's logging, this relies on
    caller discipline (a shared redaction pass is added in a later Phase 1
    commit)."""

    event_type: SecurityEventType
    actor_type: ActorType
    result: EventResult
    correlation_id: str
    occurred_at: str
    action: str
    actor_id: str | None = None
    actor_label: str | None = None
    shop_id: int | None = None
    resource: str | None = None
    request_path: str | None = None
    client_host: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_log_extra(self) -> dict[str, object]:
        """Flatten to the `extra=` dict for a stdlib log record. Standard
        fields are always present (so a log query can rely on them); optional
        fields appear only when known; metadata keys are merged at the top
        level for backward compatibility with the pre-normalization call
        sites that passed them as **kwargs."""
        extra: dict[str, object] = {
            _EVENT_FIELD: str(self.event_type),
            "actor_type": str(self.actor_type),
            "result": str(self.result),
            "correlation_id": self.correlation_id,
            "occurred_at": self.occurred_at,
            "action": self.action,
        }
        if self.actor_id is not None:
            extra["actor_id"] = self.actor_id
        if self.actor_label is not None:
            extra["actor_label"] = self.actor_label
        if self.shop_id is not None:
            extra["shop_id"] = self.shop_id
        if self.resource is not None:
            extra["resource"] = self.resource
        if self.request_path is not None:
            extra["http_path"] = self.request_path
        if self.client_host is not None:
            extra["client_host"] = self.client_host
        # Metadata last, but must not silently overwrite a standardized field.
        for key, value in self.metadata.items():
            extra.setdefault(key, value)
        return extra


def build_security_audit_event(
    event_type: SecurityEventType,
    *,
    request: Request | None = None,
    actor_type: ActorType = ActorType.ANONYMOUS,
    actor_id: object | None = None,
    actor_label: str | None = None,
    shop_id: int | None = None,
    resource: str | None = None,
    result: EventResult | None = None,
    metadata: dict[str, object] | None = None,
) -> SecurityAuditEvent:
    """Construct a normalized event, deriving correlation id (from the
    per-request context set by app/observability.py -- available even when
    `request` is not threaded through, which is why Square/billing call
    sites still get traceability without their signatures changing),
    timestamp, action (the event's namespace prefix), and default result."""
    return SecurityAuditEvent(
        event_type=event_type,
        actor_type=actor_type,
        result=result if result is not None else _default_result(event_type),
        correlation_id=request_id_var.get(),
        occurred_at=datetime.now(UTC).isoformat(),
        action=str(event_type),
        actor_id=None if actor_id is None else str(actor_id),
        actor_label=actor_label,
        shop_id=shop_id,
        resource=resource,
        request_path=(request.url.path if request is not None else None),
        client_host=(
            (request.client.host if request.client else "unknown") if request is not None else None
        ),
        metadata=dict(metadata or {}),
    )


def log_security_event(
    logger: logging.Logger,
    event_type: SecurityEventType,
    *,
    request: Request | None = None,
    level: int = logging.WARNING,
    actor_type: ActorType = ActorType.ANONYMOUS,
    actor_id: object | None = None,
    actor_label: str | None = None,
    shop_id: int | None = None,
    resource: str | None = None,
    result: EventResult | None = None,
    **fields: object,
) -> None:
    """Emit a normalized security-audit log line.

    Backward compatible: existing callers that pass only
    ``(logger, event_type, request=..., **fields)`` keep working -- their
    ``**fields`` become the event's ``metadata`` and are still flattened onto
    the log record. What is now guaranteed on *every* event, which the four
    ad-hoc shapes did not provide consistently, is: a stable
    ``security_event`` type, an ``actor_type``, a ``result``, a
    ``correlation_id`` linking back to the request-completion log line (so
    the former "Square call sites silently lack request context" gap is
    closed without threading ``request`` through more signatures), an
    ``occurred_at`` timestamp, and an ``action``.

    Callers must never pass a raw password, session token, or API key as a
    field value; this function does not sanitize its input."""
    event = build_security_audit_event(
        event_type,
        request=request,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label,
        shop_id=shop_id,
        resource=resource,
        result=result,
        metadata=fields,
    )
    logger.log(level, f"security event: {event_type.value}", extra=event.to_log_extra())
