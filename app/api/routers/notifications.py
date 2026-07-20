"""Notifications API routes.

Phase 2C Step 1 (router extraction). These three handlers were moved
verbatim from `app.main` -- identical paths, methods, response models,
dependencies, exception-to-status mapping, and store calls -- onto a bare
`APIRouter` (no prefix, no tags) so the public routes and OpenAPI contract
are unchanged. `app.main` includes this router and re-exports the handler
functions, so both the HTTP surface and the existing tests that call the
handlers directly (`main.list_notification_records`, etc.) are preserved.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSessionDep, OwnerAuthContextDep, SettingsDep
from app.models import NotificationListResponse, NotificationMarkReadResponse
from app.notification_store import (
    NotificationNotFoundError,
    NotificationStoreError,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)

logger = logging.getLogger("optimus")

router = APIRouter()


@router.get("/api/notifications", response_model=NotificationListResponse)
async def list_notification_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    unread: bool = Query(default=False),
) -> NotificationListResponse:
    try:
        return await asyncio.to_thread(
            list_notifications,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            unread_only=unread,
        )
    except NotificationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Notification listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification storage is unavailable.",
        ) from exc


@router.post(
    "/api/notifications/{notification_id}/read", response_model=NotificationMarkReadResponse
)
async def mark_notification_read_record(
    notification_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> NotificationMarkReadResponse:
    try:
        return await asyncio.to_thread(
            mark_notification_read, db=db, auth=auth, notification_id=notification_id
        )
    except NotificationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotificationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Notification mark-read failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification storage is unavailable.",
        ) from exc


@router.post("/api/notifications/read-all", response_model=NotificationMarkReadResponse)
async def mark_all_notifications_read_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> NotificationMarkReadResponse:
    try:
        return await asyncio.to_thread(mark_all_notifications_read, db=db, auth=auth)
    except NotificationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Notification mark-all-read failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification storage is unavailable.",
        ) from exc
