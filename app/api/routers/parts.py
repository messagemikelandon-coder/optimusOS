"""Parts API routes (Phase 2C Step 3).

The five /api/parts handlers were moved verbatim from app.main -- identical
paths, methods, response models, dependencies, store calls, and
exception-to-status mapping. Mounted on a bare APIRouter (no prefix, no tags)
so the public routes and OpenAPI contract are unchanged. app.main includes
this router and re-exports the handler functions, so the many tests that call
main.create_part_record(...) etc. directly keep working. Uses only the shared
app/api/deps.py aliases (owner-only CRUD with no per-group setup), so no
parts-specific dependency module is introduced.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSessionDep, OwnerAuthContextDep, SettingsDep
from app.models import (
    PartArchiveResponse,
    PartCreate,
    PartListResponse,
    PartRead,
    PartUpdate,
)
from app.part_store import (
    PartNotFoundError,
    PartStoreError,
    archive_part,
    create_part,
    get_part,
    list_parts,
    update_part,
)

logger = logging.getLogger("optimus")

router = APIRouter()


@router.post("/api/parts", response_model=PartRead)
async def create_part_record(
    payload: PartCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PartRead:
    try:
        return await asyncio.to_thread(create_part, db=db, auth=auth, payload=payload)
    except PartStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part storage is unavailable.",
        ) from exc


@router.get("/api/parts", response_model=PartListResponse)
async def list_part_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    search: str | None = Query(default=None, max_length=120),
    archived: bool = False,
    vendor_id: int | None = Query(default=None, ge=1),
    below_reorder_threshold_only: bool = False,
) -> PartListResponse:
    try:
        return await asyncio.to_thread(
            list_parts,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            archived=archived,
            search=search,
            vendor_id=vendor_id,
            below_reorder_threshold_only=below_reorder_threshold_only,
        )
    except PartStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part storage is unavailable.",
        ) from exc


@router.get("/api/parts/{part_id}", response_model=PartRead)
async def get_part_record(
    part_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PartRead:
    try:
        return await asyncio.to_thread(get_part, db=db, auth=auth, part_id=part_id)
    except PartNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PartStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part storage is unavailable.",
        ) from exc


@router.patch("/api/parts/{part_id}", response_model=PartRead)
async def update_part_record(
    part_id: int,
    payload: PartUpdate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PartRead:
    try:
        return await asyncio.to_thread(
            update_part, db=db, auth=auth, part_id=part_id, payload=payload
        )
    except PartNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PartStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part storage is unavailable.",
        ) from exc


@router.delete("/api/parts/{part_id}", response_model=PartArchiveResponse)
async def archive_part_record(
    part_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PartArchiveResponse:
    try:
        return await asyncio.to_thread(archive_part, db=db, auth=auth, part_id=part_id)
    except PartNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PartStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part archive failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part storage is unavailable.",
        ) from exc
