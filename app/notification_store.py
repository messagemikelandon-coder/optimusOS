from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_owner_id
from app.config import Settings
from app.db_models import Notification
from app.models import (
    NotificationEntityType,
    NotificationEvent,
    NotificationListResponse,
    NotificationMarkReadResponse,
    NotificationRead,
)

__all__ = [
    "NotificationNotFoundError",
    "NotificationStoreError",
    "list_notifications",
    "mark_all_notifications_read",
    "mark_notification_read",
    "record_notification",
]


class NotificationStoreError(ValueError):
    pass


class NotificationNotFoundError(NotificationStoreError):
    pass


def now_utc() -> datetime:
    return datetime.now(UTC)


def record_notification(
    *,
    db: Session,
    owner_user_id: int,
    shop_id: int | None,
    entity_type: NotificationEntityType,
    entity_id: int,
    event: NotificationEvent,
    title: str,
    body: str | None = None,
) -> None:
    """Stage a notification row on the caller's transaction. Deliberately no
    commit/flush here -- the row lands (or rolls back) together with the
    business mutation that produced it, mirroring _append_status_event.

    `shop_id` is a required kwarg (not resolved internally) because every
    caller already has the triggering row's own `shop_id` in scope --
    passing it through avoids a redundant `shop_memberships` query on this
    especially high-frequency path, and requiring it (rather than
    defaulting) forces each call site to be updated deliberately instead
    of silently falling back to a slower, previously-used lookup."""
    db.add(
        Notification(
            owner_user_id=owner_user_id,
            shop_id=shop_id,
            entity_type=entity_type.value,
            entity_id=entity_id,
            event=event.value,
            title=title[:200],
            body=body,
        )
    )


def _notification_query(auth: AuthContext) -> Select[tuple[Notification]]:
    return select(Notification).where(Notification.owner_user_id == effective_owner_id(auth))


def _to_read(notification: Notification) -> NotificationRead:
    return NotificationRead(
        id=notification.id,
        entity_type=NotificationEntityType(notification.entity_type),
        entity_id=notification.entity_id,
        event=NotificationEvent(notification.event),
        title=notification.title,
        body=notification.body,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


def _unread_count(db: Session, auth: AuthContext) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.owner_user_id == effective_owner_id(auth),
                Notification.read_at.is_(None),
            )
        )
        or 0
    )


def list_notifications(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    page: int,
    page_size: int,
    unread_only: bool,
) -> NotificationListResponse:
    if page_size > settings.notifications_max_page_size:
        raise NotificationStoreError(
            f"Page size exceeds the maximum of {settings.notifications_max_page_size}."
        )
    if page < 1:
        raise NotificationStoreError("Page must be 1 or greater.")
    query = _notification_query(auth)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    offset = (page - 1) * page_size
    items = db.scalars(
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()
    return NotificationListResponse(
        items=[_to_read(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        unread_count=_unread_count(db, auth),
        has_more=offset + len(items) < total,
    )


def mark_notification_read(
    *,
    db: Session,
    auth: AuthContext,
    notification_id: int,
) -> NotificationMarkReadResponse:
    notification = db.scalar(_notification_query(auth).where(Notification.id == notification_id))
    if notification is None:
        raise NotificationNotFoundError("Notification not found.")
    if notification.read_at is None:
        notification.read_at = now_utc()
        db.add(notification)
        db.commit()
    return NotificationMarkReadResponse(ok=True, unread_count=_unread_count(db, auth))


def mark_all_notifications_read(
    *,
    db: Session,
    auth: AuthContext,
) -> NotificationMarkReadResponse:
    unread = db.scalars(_notification_query(auth).where(Notification.read_at.is_(None))).all()
    stamp = now_utc()
    for notification in unread:
        notification.read_at = stamp
        db.add(notification)
    if unread:
        db.commit()
    return NotificationMarkReadResponse(ok=True, unread_count=_unread_count(db, auth))
