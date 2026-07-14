from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import FastAPI, Request, Response

# Standard LogRecord attributes -- anything else on a record was passed via
# logger.info(..., extra={...}) and belongs in the structured JSON output.
_STANDARD_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdLogFilter(logging.Filter):
    """Attaches the current request's id to every log record emitted while
    handling it, including log lines from deep inside store/service code
    that have no direct access to the Request object."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


class JsonLogFormatter(logging.Formatter):
    """Structured JSON logging for production log aggregation. Emits only
    request_id/path/method/status/duration/error-classification style
    operational fields -- callers are responsible for never passing
    passwords, tokens, or customer-sensitive text through `extra` (existing
    call sites in this codebase already sanitize exception messages before
    logging; this formatter does not add new content, only structure)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and key != "request_id":
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str)


def configure_structured_logging(log_level: str) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    handler.addFilter(RequestIdLogFilter())
    root_logger.handlers = [handler]


def install_request_context_middleware(app: FastAPI, logger: logging.Logger) -> None:
    @app.middleware("http")
    async def request_context_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid.uuid4())
        token = request_id_var.set(request_id)
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # Logged (and the contextvar reset) here, inside the except
            # block, while request_id_var is still set for this task --
            # resetting in a finally would run before this log line on the
            # success path below and silently drop the request_id from it.
            logger.exception(
                "Unhandled exception",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "error_category": "unhandled_exception",
                },
            )
            request_id_var.reset(token)
            raise
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request completed",
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        request_id_var.reset(token)
        return response
