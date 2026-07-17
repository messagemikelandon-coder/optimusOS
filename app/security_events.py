from __future__ import annotations

import logging
from enum import StrEnum

from fastapi import Request

_EVENT_FIELD = "security_event"


class SecurityEventType(StrEnum):
    """The Phase 6 Part H security-event taxonomy. Scoped to events this
    codebase can actually emit today -- billing-webhook failures and
    per-shop OpenAI cost are explicitly out of scope until billing and a
    multi-shop/tenant model exist (see docs/context/THREAT_MODEL.md)."""

    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    RATE_LIMIT_EXCEEDED = "rate_limit.exceeded"
    SQUARE_API_FAILED = "square.api_failed"


def log_security_event(
    logger: logging.Logger,
    event_type: SecurityEventType,
    *,
    request: Request | None = None,
    level: int = logging.WARNING,
    **fields: object,
) -> None:
    """Structured, machine-filterable security logging: every call tags the
    line with a fixed `security_event` field so a log aggregator can
    alert/dashboard on this taxonomy independently of free-text log
    messages, on top of the generic request-correlation logging
    `app/observability.py` already provides. Callers must never pass raw
    passwords, session tokens, or API keys as a field value -- this
    function does not sanitize its input, the same discipline every other
    structured log call site in this codebase already follows."""
    extra: dict[str, object] = {_EVENT_FIELD: str(event_type), **fields}
    if request is not None:
        extra.setdefault("http_path", request.url.path)
        extra.setdefault("client_host", request.client.host if request.client else "unknown")
    logger.log(level, f"security event: {event_type.value}", extra=extra)
