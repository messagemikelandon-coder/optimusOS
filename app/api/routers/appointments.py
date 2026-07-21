"""Appointments API routes (Phase 2C Step 8).

The six /api/appointments handlers were moved verbatim from app.main --
identical paths, methods, response models, dependencies, store calls, and
exception-to-status mapping. Mounted on a bare APIRouter (no prefix, no
tags) so the public routes and OpenAPI contract are unchanged. app.main
includes this router and re-exports the handler functions, so the tests
that call main.create_appointment_record(...) etc. directly keep working.
Uses only the shared app/api/deps.py aliases -- all six routes are
owner-only (OwnerAuthContextDep); there is currently no technician-facing
appointment endpoint (OwnerOrTechnicianAuthContextDep is used elsewhere in
app.main, e.g. technician time entries, but never for /api/appointments),
so a future Technician Mode assigned-appointment view would be new surface,
not a route already present here.

app/scheduling_store.py is shared by appointments, bays, working hours, and
schedule blocks; only the six appointment-specific store functions are
imported here, and the store module itself -- including get_availability(),
which reads the Appointment table directly (alongside WorkingHours and
ScheduleBlock) for the /api/availability endpoint that stays in app.main --
is untouched. Appointment conflict detection (working-hours, technician
overlap, bay overlap, schedule-block overlap), the customer/vehicle/
technician/bay/work-order relationship validation, and the row-locking used
to serialize concurrent conflict-check-then-insert requests all live
entirely in the store and are unaffected by this route-layer move.

Mode classification (routing only, no gating added here): Solo Mode already
works today since technician_id/bay_id are the only required scheduling
FKs and an owner can be their own technician record; Mobile Field Mode
appointments use the existing service_location field with no travel/
service-area fields yet (a real model limitation, not addressed here);
Shop Mode is the primary current use (technician + bay); Technician Mode's
assigned-appointment view does not exist as a route today (see above).
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
    AppointmentCancelRequest,
    AppointmentCreate,
    AppointmentListResponse,
    AppointmentMoveRequest,
    AppointmentRead,
    AppointmentStatus,
    AppointmentUpdate,
)
from app.scheduling_store import (
    SchedulingConflictError,
    SchedulingNotFoundError,
    SchedulingStoreError,
    cancel_appointment,
    create_appointment,
    get_appointment,
    list_appointments,
    move_appointment,
    update_appointment,
)

logger = logging.getLogger("optimus")

router = APIRouter()


@router.post("/api/appointments", response_model=AppointmentRead)
async def create_appointment_record(
    payload: AppointmentCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> AppointmentRead:
    try:
        return await asyncio.to_thread(create_appointment, db=db, auth=auth, payload=payload)
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SchedulingConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Appointment creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.get("/api/appointments", response_model=AppointmentListResponse)
async def list_appointment_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=50),
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
    technician_id: int | None = Query(default=None),
    bay_id: int | None = Query(default=None),
    status_filter: Annotated[AppointmentStatus | None, Query(alias="status")] = None,
    customer_id: int | None = Query(default=None),
    vehicle_id: int | None = Query(default=None),
) -> AppointmentListResponse:
    try:
        return await asyncio.to_thread(
            list_appointments,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            date_from=date_from,
            date_to=date_to,
            technician_id=technician_id,
            bay_id=bay_id,
            status_filter=status_filter,
            customer_id=customer_id,
            vehicle_id=vehicle_id,
        )
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Appointment listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.get("/api/appointments/{appointment_id}", response_model=AppointmentRead)
async def get_appointment_record(
    appointment_id: int, db: DbSessionDep, auth: OwnerAuthContextDep
) -> AppointmentRead:
    try:
        return await asyncio.to_thread(
            get_appointment, db=db, auth=auth, appointment_id=appointment_id
        )
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Appointment retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.patch("/api/appointments/{appointment_id}", response_model=AppointmentRead)
async def update_appointment_record(
    appointment_id: int,
    payload: AppointmentUpdate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> AppointmentRead:
    try:
        return await asyncio.to_thread(
            update_appointment, db=db, auth=auth, appointment_id=appointment_id, payload=payload
        )
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SchedulingConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Appointment update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.post("/api/appointments/{appointment_id}/move", response_model=AppointmentRead)
async def move_appointment_record(
    appointment_id: int,
    payload: AppointmentMoveRequest,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> AppointmentRead:
    try:
        return await asyncio.to_thread(
            move_appointment, db=db, auth=auth, appointment_id=appointment_id, payload=payload
        )
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SchedulingConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Appointment move failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


@router.post("/api/appointments/{appointment_id}/cancel", response_model=AppointmentRead)
async def cancel_appointment_record(
    appointment_id: int,
    payload: AppointmentCancelRequest,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> AppointmentRead:
    try:
        return await asyncio.to_thread(
            cancel_appointment,
            db=db,
            auth=auth,
            appointment_id=appointment_id,
            cancellation_reason=payload.cancellation_reason,
        )
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SchedulingConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.as_detail()) from exc
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Appointment cancellation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc
