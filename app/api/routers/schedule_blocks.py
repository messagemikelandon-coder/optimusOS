"""Schedule-blocks API routes (Phase 2C Step 7).

The five /api/schedule-blocks handlers were moved verbatim from app.main --
identical paths, methods, response models, dependencies, store calls, and
exception-to-status mapping. Mounted on a bare APIRouter (no prefix, no
tags) so the public routes and OpenAPI contract are unchanged. app.main
includes this router and re-exports the handler functions, so the tests
that call main.create_schedule_block_record(...) etc. directly keep
working. Uses only the shared app/api/deps.py aliases (owner-only CRUD
with no per-group setup), so no schedule-block-specific dependency module
is introduced. app/scheduling_store.py is shared by schedule blocks, bays,
working hours, and appointments; only the five schedule-block-specific
store functions are imported here, and the store module itself --
including get_availability(), which reads the ScheduleBlock table directly
for the /api/availability endpoint that stays in app.main -- is untouched.

Mode classification (routing only, no gating added here): a schedule block
with neither technician_id nor bay_id set represents owner-level
unavailability (Solo Mode, and Mobile Field Mode's travel/parts-pickup/
service-area windows once technician_id is set for a mobile technician);
a block with bay_id set represents shop closures or equipment/bay downtime
(Shop Mode); a block with technician_id set represents a technician
constraint usable by a future Technician Mode read-only view. All three
are already served by this same store shape -- no schema or route change
is needed to support them later.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSessionDep, OwnerAuthContextDep, SettingsDep
from app.models import (
    ScheduleBlockCreate,
    ScheduleBlockListResponse,
    ScheduleBlockRead,
    ScheduleBlockUpdate,
)
from app.scheduling_store import (
    SchedulingNotFoundError,
    SchedulingStoreError,
    create_schedule_block,
    delete_schedule_block,
    get_schedule_block,
    list_schedule_blocks,
    update_schedule_block,
)

logger = logging.getLogger("optimus")

router = APIRouter()


@router.post("/api/schedule-blocks", response_model=ScheduleBlockRead)
async def create_schedule_block_record(
    payload: ScheduleBlockCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> ScheduleBlockRead:
    try:
        return await asyncio.to_thread(create_schedule_block, db=db, auth=auth, payload=payload)
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Schedule block creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.get("/api/schedule-blocks", response_model=ScheduleBlockListResponse)
async def list_schedule_block_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    technician_id: int | None = Query(default=None),
    bay_id: int | None = Query(default=None),
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> ScheduleBlockListResponse:
    try:
        return await asyncio.to_thread(
            list_schedule_blocks,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            technician_id=technician_id,
            bay_id=bay_id,
            date_from=date_from,
            date_to=date_to,
        )
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Schedule block listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.get("/api/schedule-blocks/{block_id}", response_model=ScheduleBlockRead)
async def get_schedule_block_record(
    block_id: int, db: DbSessionDep, auth: OwnerAuthContextDep
) -> ScheduleBlockRead:
    try:
        return await asyncio.to_thread(get_schedule_block, db=db, auth=auth, block_id=block_id)
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Schedule block retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.patch("/api/schedule-blocks/{block_id}", response_model=ScheduleBlockRead)
async def update_schedule_block_record(
    block_id: int,
    payload: ScheduleBlockUpdate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> ScheduleBlockRead:
    try:
        return await asyncio.to_thread(
            update_schedule_block, db=db, auth=auth, block_id=block_id, payload=payload
        )
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Schedule block update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.delete("/api/schedule-blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule_block_record(
    block_id: int, db: DbSessionDep, auth: OwnerAuthContextDep
) -> None:
    try:
        await asyncio.to_thread(delete_schedule_block, db=db, auth=auth, block_id=block_id)
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Schedule block deletion failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc
