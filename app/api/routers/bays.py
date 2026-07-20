"""Bays API routes (Phase 2C Step 5).

The five /api/bays handlers were moved verbatim from app.main -- identical
paths, methods, response models, dependencies, store calls, and
exception-to-status mapping. Mounted on a bare APIRouter (no prefix, no tags)
so the public routes and OpenAPI contract are unchanged. app.main includes
this router and re-exports the handler functions, so the tests that call
main.create_bay_record(...) etc. directly keep working. Uses only the shared
app/api/deps.py aliases (owner-only CRUD with no per-group setup), so no
bay-specific dependency module is introduced. app/scheduling_store.py is
shared by bays, appointments, schedule blocks, and working hours; only the
five bay-specific store functions are imported here, and the store module
itself is untouched. Bays are Shop Mode functionality (multi-bay capacity is
irrelevant to Solo Mode and typically to Mobile Field Mode); this extraction
does not add mode gating -- it only relocates the route handlers.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSessionDep, OwnerAuthContextDep, SettingsDep
from app.models import (
    BayArchiveResponse,
    BayCreate,
    BayListResponse,
    BayRead,
    BayUpdate,
)
from app.scheduling_store import (
    SchedulingNotFoundError,
    SchedulingStoreError,
    archive_bay,
    create_bay,
    get_bay,
    list_bays,
    update_bay,
)

logger = logging.getLogger("optimus")

router = APIRouter()


@router.post("/api/bays", response_model=BayRead)
async def create_bay_record(
    payload: BayCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> BayRead:
    try:
        return await asyncio.to_thread(create_bay, db=db, auth=auth, payload=payload)
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Bay creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bay storage is unavailable."
        ) from exc


@router.get("/api/bays", response_model=BayListResponse)
async def list_bay_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    archived: bool = False,
) -> BayListResponse:
    try:
        return await asyncio.to_thread(
            list_bays,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            archived=archived,
        )
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Bay listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bay storage is unavailable."
        ) from exc


@router.get("/api/bays/{bay_id}", response_model=BayRead)
async def get_bay_record(bay_id: int, db: DbSessionDep, auth: OwnerAuthContextDep) -> BayRead:
    try:
        return await asyncio.to_thread(get_bay, db=db, auth=auth, bay_id=bay_id)
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Bay retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bay storage is unavailable."
        ) from exc


@router.patch("/api/bays/{bay_id}", response_model=BayRead)
async def update_bay_record(
    bay_id: int,
    payload: BayUpdate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> BayRead:
    try:
        return await asyncio.to_thread(update_bay, db=db, auth=auth, bay_id=bay_id, payload=payload)
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Bay update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bay storage is unavailable."
        ) from exc


@router.delete("/api/bays/{bay_id}", response_model=BayArchiveResponse)
async def archive_bay_record(
    bay_id: int, db: DbSessionDep, auth: OwnerAuthContextDep
) -> BayArchiveResponse:
    try:
        return await asyncio.to_thread(archive_bay, db=db, auth=auth, bay_id=bay_id)
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Bay archive failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bay storage is unavailable."
        ) from exc
