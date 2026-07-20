"""Context API routes (Phase 2C Step 2).

The three /api/context handlers were moved verbatim from app.main -- identical
paths, methods, response models, dependencies, `ensure_context_dependencies`
call, store calls, and exception-to-status mapping (including the DELETE
handler's existing "not found" message check, preserved exactly; changing it
is out of scope for this extraction). Mounted on a bare APIRouter (no prefix,
no tags) so the public routes and OpenAPI contract are unchanged. app.main
includes this router and re-exports the handler functions so existing tests
calling main.get_context(...) etc. keep working.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.context_deps import ensure_context_dependencies
from app.api.deps import DbSessionDep, SettingsDep, VerifiedAuthContextDep
from app.context_store import (
    ContextCapacityError,
    ContextConflictError,
    ContextStoreError,
    delete_entry,
    list_entries,
    upsert_entry,
)
from app.models import (
    ContextDeleteResponse,
    ContextEntryRead,
    ContextEntryUpsertRequest,
    ContextListResponse,
    ContextScope,
)

logger = logging.getLogger("optimus")

router = APIRouter()


@router.get("/api/context/{project_key}", response_model=ContextListResponse)
async def get_context(
    project_key: str,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: VerifiedAuthContextDep,
    scope: ContextScope = ContextScope.PROJECT,
) -> ContextListResponse:
    await asyncio.to_thread(ensure_context_dependencies, settings)
    try:
        return await asyncio.to_thread(
            list_entries,
            db=db,
            auth=auth,
            settings=settings,
            project_key=project_key,
            scope=scope,
        )
    except ContextStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Context listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Context storage is unavailable.",
        ) from exc


@router.put("/api/context/{project_key}/{context_key}", response_model=ContextEntryRead)
async def put_context(
    project_key: str,
    context_key: str,
    payload: ContextEntryUpsertRequest,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: VerifiedAuthContextDep,
    scope: ContextScope = ContextScope.PROJECT,
) -> ContextEntryRead:
    await asyncio.to_thread(ensure_context_dependencies, settings)
    try:
        return await asyncio.to_thread(
            upsert_entry,
            db=db,
            auth=auth,
            settings=settings,
            project_key=project_key,
            scope=scope,
            context_key=context_key,
            value=payload.value,
            expected_revision=payload.expected_revision,
        )
    except ContextConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ContextCapacityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ContextStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Context upsert failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Context storage is unavailable.",
        ) from exc


@router.delete("/api/context/{project_key}/{context_key}", response_model=ContextDeleteResponse)
async def remove_context(
    project_key: str,
    context_key: str,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: VerifiedAuthContextDep,
    scope: ContextScope = ContextScope.PROJECT,
    expected_revision: int | None = None,
) -> ContextDeleteResponse:
    await asyncio.to_thread(ensure_context_dependencies, settings)
    try:
        return await asyncio.to_thread(
            delete_entry,
            db=db,
            auth=auth,
            settings=settings,
            project_key=project_key,
            scope=scope,
            context_key=context_key,
            expected_revision=expected_revision,
        )
    except ContextConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ContextStoreError as exc:
        status_code_value = 404 if "not found" in str(exc).lower() else 422
        raise HTTPException(status_code=status_code_value, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Context deletion failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Context storage is unavailable.",
        ) from exc
