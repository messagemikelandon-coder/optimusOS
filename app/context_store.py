from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_owner_id, ensure_utc
from app.config import Settings
from app.db_models import ContextEntry
from app.models import ContextDeleteResponse, ContextEntryRead, ContextListResponse, ContextScope

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bOPENAI_API_KEY\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b", re.IGNORECASE),
    re.compile(r"\boptimus_session=", re.IGNORECASE),
    re.compile(r"\bpassword\s*[:=]\s*\S+", re.IGNORECASE),
)


class ContextStoreError(ValueError):
    pass


class ContextConflictError(ContextStoreError):
    pass


class ContextCapacityError(ContextStoreError):
    pass


@dataclass(frozen=True, slots=True)
class NormalizedScope:
    project_key: str
    scope: ContextScope
    scope_key: str
    auth_session_id: int | None


def normalize_identifier(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    if not _IDENTIFIER_RE.fullmatch(normalized):
        raise ContextStoreError(
            f"{field_name} must start with a letter or digit and use only letters, digits, '.', '_', or '-'."
        )
    return normalized


def validate_context_value(value: str, settings: Settings) -> str:
    normalized = value.strip()
    if len(normalized) > settings.context_max_value_chars:
        raise ContextStoreError(
            f"Context value exceeds the {settings.context_max_value_chars}-character limit."
        )
    for pattern in _SECRET_PATTERNS:
        if pattern.search(normalized):
            raise ContextStoreError("Context values must not store secrets, tokens, or passwords.")
    return normalized


def normalize_scope(project_key: str, scope: ContextScope, auth: AuthContext) -> NormalizedScope:
    normalized_project = normalize_identifier(project_key, field_name="project_key")
    if scope is ContextScope.PROJECT:
        return NormalizedScope(
            project_key=normalized_project,
            scope=scope,
            scope_key=f"project:{normalized_project}",
            auth_session_id=None,
        )
    return NormalizedScope(
        project_key=normalized_project,
        scope=scope,
        scope_key=f"project:{normalized_project}:session:{auth.session.id}",
        auth_session_id=auth.session.id,
    )


def stale_cutoff(settings: Settings) -> datetime:
    return datetime.now(UTC) - timedelta(hours=settings.context_stale_after_hours)


def _base_query(
    db: Session,
    auth: AuthContext,
    normalized_scope: NormalizedScope,
) -> Select[tuple[ContextEntry]]:
    return (
        select(ContextEntry)
        .where(ContextEntry.user_id == effective_shop_owner_id(db, auth))
        .where(ContextEntry.project_key == normalized_scope.project_key)
        .where(ContextEntry.scope_type == normalized_scope.scope.value)
        .where(ContextEntry.scope_key == normalized_scope.scope_key)
    )


def _entry_to_read(entry: ContextEntry, settings: Settings) -> ContextEntryRead:
    updated_at = ensure_utc(entry.updated_at)
    return ContextEntryRead(
        id=entry.id,
        project_key=entry.project_key,
        scope=ContextScope(entry.scope_type),
        context_key=entry.context_key,
        value=entry.value,
        revision=entry.revision,
        updated_at=updated_at,
        stale=updated_at < stale_cutoff(settings),
    )


def list_entries(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    project_key: str,
    scope: ContextScope,
) -> ContextListResponse:
    normalized_scope = normalize_scope(project_key, scope, auth)
    entries: list[ContextEntry]
    if scope is ContextScope.SESSION:
        session_entries = db.scalars(
            _base_query(db, auth, normalized_scope).order_by(
                ContextEntry.updated_at.desc(),
                ContextEntry.id.desc(),
            )
        ).all()
        project_scope = normalize_scope(project_key, ContextScope.PROJECT, auth)
        project_entries = db.scalars(
            _base_query(db, auth, project_scope).order_by(
                ContextEntry.updated_at.desc(),
                ContextEntry.id.desc(),
            )
        ).all()
        seen_keys = {entry.context_key for entry in session_entries}
        entries = [
            *session_entries,
            *(entry for entry in project_entries if entry.context_key not in seen_keys),
        ]
    else:
        entries = list(
            db.scalars(
                _base_query(db, auth, normalized_scope).order_by(
                    ContextEntry.updated_at.desc(),
                    ContextEntry.id.desc(),
                )
            ).all()
        )
    return ContextListResponse(
        project_key=normalized_scope.project_key,
        scope=scope,
        entries=[_entry_to_read(entry, settings) for entry in entries],
        max_entries=settings.context_max_entries_per_scope,
        stale_after_hours=settings.context_stale_after_hours,
    )


def upsert_entry(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    project_key: str,
    scope: ContextScope,
    context_key: str,
    value: str,
    expected_revision: int | None,
) -> ContextEntryRead:
    normalized_scope = normalize_scope(project_key, scope, auth)
    normalized_key = normalize_identifier(context_key, field_name="context_key")
    normalized_value = validate_context_value(value, settings)
    existing = db.scalar(
        _base_query(db, auth, normalized_scope).where(ContextEntry.context_key == normalized_key)
    )
    if existing is not None:
        if expected_revision is not None and existing.revision != expected_revision:
            raise ContextConflictError(
                f"Context entry revision mismatch. Expected {expected_revision}, found {existing.revision}."
            )
        existing.value = normalized_value
        existing.revision += 1
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return _entry_to_read(existing, settings)

    count = db.scalar(
        select(func.count())
        .select_from(ContextEntry)
        .where(ContextEntry.user_id == effective_shop_owner_id(db, auth))
        .where(ContextEntry.scope_type == normalized_scope.scope.value)
        .where(ContextEntry.scope_key == normalized_scope.scope_key)
    )
    if count is not None and count >= settings.context_max_entries_per_scope:
        raise ContextCapacityError(
            f"Context scope already contains {settings.context_max_entries_per_scope} entries."
        )

    entry = ContextEntry(
        user_id=effective_shop_owner_id(db, auth),
        auth_session_id=normalized_scope.auth_session_id,
        project_key=normalized_scope.project_key,
        scope_type=normalized_scope.scope.value,
        scope_key=normalized_scope.scope_key,
        context_key=normalized_key,
        value=normalized_value,
        revision=1,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _entry_to_read(entry, settings)


def delete_entry(
    *,
    db: Session,
    auth: AuthContext,
    settings: Settings,
    project_key: str,
    scope: ContextScope,
    context_key: str,
    expected_revision: int | None,
) -> ContextDeleteResponse:
    normalized_scope = normalize_scope(project_key, scope, auth)
    normalized_key = normalize_identifier(context_key, field_name="context_key")
    entry = db.scalar(
        _base_query(db, auth, normalized_scope).where(ContextEntry.context_key == normalized_key)
    )
    if entry is None:
        raise ContextStoreError("Context entry was not found.")
    if expected_revision is not None and entry.revision != expected_revision:
        raise ContextConflictError(
            f"Context entry revision mismatch. Expected {expected_revision}, found {entry.revision}."
        )
    deleted_revision = entry.revision
    db.delete(entry)
    db.commit()
    return ContextDeleteResponse(
        project_key=normalized_scope.project_key,
        scope=scope,
        context_key=normalized_key,
        deleted_revision=deleted_revision,
    )
