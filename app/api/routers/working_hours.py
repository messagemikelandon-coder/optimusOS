"""Working-hours API routes (Phase 2C Step 6).

The four /api/working-hours handlers were moved verbatim from app.main --
identical paths, methods, response models, dependencies, store calls, and
exception-to-status mapping. Mounted on a bare APIRouter (no prefix, no
tags) so the public routes and OpenAPI contract are unchanged. app.main
includes this router and re-exports the handler functions, so the tests
that call main.create_working_hours_record(...) etc. directly keep
working. Uses only the shared app/api/deps.py aliases (owner-only CRUD
with no per-group setup), so no working-hours-specific dependency module
is introduced. app/scheduling_store.py is shared by working hours, bays,
appointments, and schedule blocks; only the four working-hours-specific
store functions are imported here, and the store module itself --
including get_availability(), which reads the WorkingHours table directly
for the /api/availability endpoint that stays in app.main -- is untouched.

Mode classification (routing only, no gating added here): owner working
hours apply in Solo Mode without bays/technicians; Shop Mode uses them
alongside bays/technicians; Mobile Field Mode's field availability/travel
windows and a future Technician Mode's per-technician availability are
both still backed by this same technician_id-keyed WorkingHours store, so
no schema or route change is needed to support them later.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSessionDep, OwnerAuthContextDep
from app.models import (
    WorkingHoursCreate,
    WorkingHoursListResponse,
    WorkingHoursRead,
    WorkingHoursUpdate,
)
from app.scheduling_store import (
    SchedulingNotFoundError,
    SchedulingStoreError,
    create_working_hours,
    delete_working_hours,
    list_working_hours,
    update_working_hours,
)

logger = logging.getLogger("optimus")

router = APIRouter()


@router.post("/api/working-hours", response_model=WorkingHoursRead)
async def create_working_hours_record(
    payload: WorkingHoursCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> WorkingHoursRead:
    try:
        return await asyncio.to_thread(create_working_hours, db=db, auth=auth, payload=payload)
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Working hours creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.get("/api/working-hours", response_model=WorkingHoursListResponse)
async def list_working_hours_records(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
    technician_id: int = Query(...),
) -> WorkingHoursListResponse:
    try:
        return await asyncio.to_thread(
            list_working_hours, db=db, auth=auth, technician_id=technician_id
        )
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Working hours listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.patch("/api/working-hours/{working_hours_id}", response_model=WorkingHoursRead)
async def update_working_hours_record(
    working_hours_id: int,
    payload: WorkingHoursUpdate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> WorkingHoursRead:
    try:
        return await asyncio.to_thread(
            update_working_hours,
            db=db,
            auth=auth,
            working_hours_id=working_hours_id,
            payload=payload,
        )
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Working hours update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.delete("/api/working-hours/{working_hours_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_working_hours_record(
    working_hours_id: int, db: DbSessionDep, auth: OwnerAuthContextDep
) -> None:
    try:
        await asyncio.to_thread(
            delete_working_hours, db=db, auth=auth, working_hours_id=working_hours_id
        )
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Working hours deletion failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc
