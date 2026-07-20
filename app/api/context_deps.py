"""Context-management dependency guard (Phase 2C Step 2).

`ensure_context_dependencies` was defined in app/main.py and called by the
/api/context handlers. It moves here -- a narrow leaf module -- so the
extracted context router can use it without importing app.main. This module
imports only leaf modules (app.net, app.config) and fastapi; it never
imports app.main or any router.

Behavior is byte-for-byte the same as the former app.main version: a no-op
in the test environment, otherwise a 503 with the same structured detail if
Postgres or Redis is unreachable.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.config import Settings
from app.net import _tcp_dependency_ready


def ensure_context_dependencies(settings: Settings) -> None:
    if settings.app_env == "test":
        return
    unavailable: list[str] = []
    if not _tcp_dependency_ready(settings.database_url, 5432):
        unavailable.append("postgres")
    if not _tcp_dependency_ready(settings.redis_url, 6379):
        unavailable.append("redis")
    if unavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "context_dependencies_unavailable",
                "message": "Context management dependencies are unavailable.",
                "unavailable_dependencies": unavailable,
            },
        )
