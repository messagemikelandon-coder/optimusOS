"""Technicians API routes (Phase 2C Step 9).

The nine /api/technicians handlers were moved verbatim from app.main --
identical paths, methods, response models, dependencies, store calls, and
exception-to-status mapping. Mounted on a bare APIRouter (no prefix, no
tags) so the public routes and OpenAPI contract are unchanged. app.main
includes this router and re-exports the handler functions, so the tests
that call main.create_technician_record(...) etc. directly keep working.

Unlike every prior extraction in this series, this group is not
owner-only: six routes (create, list, get-by-id, update, archive,
provision-login) use OwnerAuthContextDep, but three self-service routes
(GET /me, POST /me/clock-in, POST /me/clock-out) use
OwnerOrTechnicianAuthContextDep -- a technician can read their own profile
and clock in/out, but cannot manage the technician roster. Both aliases
are shared app/api/deps.py aliases already used elsewhere in app.main, so
no new dependency module is introduced.

app/technician_store.py is imported directly (not through app.main) by
several other stores -- part_allocation_store, work_order_store,
diagnostics_store, inspection_store, scheduling_store (all via
get_technician_for_user/display_name), account_security_store (via
TechnicianConflictError/enforce_technician_seat_limit), and
test_support_store (via create_technician/provision_login for synthetic
account provisioning). None of those go through app.main or this router,
so moving the nine route handlers out of app.main does not affect them.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import (
    DbSessionDep,
    OwnerAuthContextDep,
    OwnerOrTechnicianAuthContextDep,
    SettingsDep,
)
from app.models import (
    TechnicianArchiveResponse,
    TechnicianClockResponse,
    TechnicianCreate,
    TechnicianListResponse,
    TechnicianMeResponse,
    TechnicianProvisionLoginRequest,
    TechnicianProvisionLoginResponse,
    TechnicianRead,
    TechnicianUpdate,
)
from app.technician_store import (
    TechnicianConflictError,
    TechnicianNotFoundError,
    TechnicianStoreError,
    archive_technician,
    clock_in,
    clock_out,
    create_technician,
    get_my_technician_profile,
    get_technician,
    list_technicians,
    provision_login,
    update_technician,
)

logger = logging.getLogger("optimus")

router = APIRouter()


@router.post("/api/technicians", response_model=TechnicianRead)
async def create_technician_record(
    payload: TechnicianCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> TechnicianRead:
    try:
        return await asyncio.to_thread(create_technician, db=db, auth=auth, payload=payload)
    except TechnicianStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Technician creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Technician storage is unavailable.",
        ) from exc


@router.get("/api/technicians", response_model=TechnicianListResponse)
async def list_technician_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    search: str | None = Query(default=None, max_length=120),
    archived: bool = False,
) -> TechnicianListResponse:
    try:
        return await asyncio.to_thread(
            list_technicians,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            archived=archived,
            search=search,
        )
    except TechnicianStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Technician listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Technician storage is unavailable.",
        ) from exc


@router.get("/api/technicians/me", response_model=TechnicianMeResponse)
async def get_my_technician_record(
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> TechnicianMeResponse:
    try:
        return await asyncio.to_thread(get_my_technician_profile, db=db, auth=auth)
    except TechnicianNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Technician self-profile lookup failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Technician storage is unavailable.",
        ) from exc


@router.post("/api/technicians/me/clock-in", response_model=TechnicianClockResponse)
async def clock_in_record(
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> TechnicianClockResponse:
    try:
        return await asyncio.to_thread(clock_in, db=db, auth=auth)
    except TechnicianNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TechnicianConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Technician clock-in failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Technician storage is unavailable.",
        ) from exc


@router.post("/api/technicians/me/clock-out", response_model=TechnicianClockResponse)
async def clock_out_record(
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> TechnicianClockResponse:
    try:
        return await asyncio.to_thread(clock_out, db=db, auth=auth)
    except TechnicianNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TechnicianConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Technician clock-out failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Technician storage is unavailable.",
        ) from exc


@router.get("/api/technicians/{technician_id}", response_model=TechnicianRead)
async def get_technician_record(
    technician_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> TechnicianRead:
    try:
        return await asyncio.to_thread(
            get_technician, db=db, auth=auth, technician_id=technician_id
        )
    except TechnicianNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TechnicianStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Technician retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Technician storage is unavailable.",
        ) from exc


@router.patch("/api/technicians/{technician_id}", response_model=TechnicianRead)
async def update_technician_record(
    technician_id: int,
    payload: TechnicianUpdate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> TechnicianRead:
    try:
        return await asyncio.to_thread(
            update_technician, db=db, auth=auth, technician_id=technician_id, payload=payload
        )
    except TechnicianNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TechnicianStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Technician update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Technician storage is unavailable.",
        ) from exc


@router.delete("/api/technicians/{technician_id}", response_model=TechnicianArchiveResponse)
async def archive_technician_record(
    technician_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> TechnicianArchiveResponse:
    try:
        return await asyncio.to_thread(
            archive_technician, db=db, auth=auth, technician_id=technician_id
        )
    except TechnicianNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TechnicianStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Technician archive failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Technician storage is unavailable.",
        ) from exc


@router.post(
    "/api/technicians/{technician_id}/provision-login",
    response_model=TechnicianProvisionLoginResponse,
)
async def provision_technician_login_record(
    technician_id: int,
    payload: TechnicianProvisionLoginRequest,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> TechnicianProvisionLoginResponse:
    try:
        return await asyncio.to_thread(
            provision_login, db=db, auth=auth, technician_id=technician_id, payload=payload
        )
    except TechnicianNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TechnicianConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TechnicianStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Technician login provisioning failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Technician storage is unavailable.",
        ) from exc
