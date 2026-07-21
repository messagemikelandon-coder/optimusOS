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
irrelevant to Solo Mode and typically to Mobile Field Mode).

ADR-022 capability observe pilot: each handler additionally calls the
central capability gate (app/capability_gate.py) in OBSERVE mode via
`_observe_bays`, after the existing owner-or-manager auth gate has already
admitted the caller. OBSERVE only records what a future enforcement pass
over `CapabilityId.BAYS` *would* decide (would_allow in Shop mode,
would_deny in Solo/Mobile Field) as one structured telemetry event -- it
never changes behaviour, never raises, and never touches bay data, so every
response is byte-identical with or without the pilot. Bays is the only route
group wired to the gate, and only in OBSERVE; an AST safeguard
(tests/test_capability_gate_safeguards.py) fails the build if any route
activates ENFORCE. See the OBSERVE->ENFORCE runbook in
docs/architecture/OPERATING-MODES-ARCHITECTURE-BRIDGE.md.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSessionDep, OwnerAuthContextDep, SettingsDep
from app.capability_gate import CapabilityGateMode, evaluate_capability
from app.models import (
    BayArchiveResponse,
    BayCreate,
    BayListResponse,
    BayRead,
    BayUpdate,
    CapabilityId,
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


async def _observe_bays(db: DbSessionDep, auth: OwnerAuthContextDep, action: str) -> None:
    """ADR-022 observe-only capability pilot. Runs after the route's existing
    auth/role/tenant gate has already admitted the caller, and records what a
    future ENFORCE pass over `CapabilityId.BAYS` would decide -- without ever
    changing this request's behavior (OBSERVE never raises; the handler
    proceeds to its normal store call regardless of the observed decision).
    Bays are Shop-mode functionality, so a Solo/Mobile Field shop resolves to
    would_deny/hidden here while still being served identically today. Bays
    is deliberately the only route group wired to the gate in this slice, and
    only in OBSERVE mode.
    """
    await asyncio.to_thread(
        evaluate_capability,
        db,
        auth,
        CapabilityId.BAYS,
        action=action,
        mode=CapabilityGateMode.OBSERVE,
    )


@router.post("/api/bays", response_model=BayRead)
async def create_bay_record(
    payload: BayCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> BayRead:
    await _observe_bays(db, auth, "bays.create")
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
    await _observe_bays(db, auth, "bays.list")
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
    await _observe_bays(db, auth, "bays.get")
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
    await _observe_bays(db, auth, "bays.update")
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
    await _observe_bays(db, auth, "bays.archive")
    try:
        return await asyncio.to_thread(archive_bay, db=db, auth=auth, bay_id=bay_id)
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Bay archive failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Bay storage is unavailable."
        ) from exc
