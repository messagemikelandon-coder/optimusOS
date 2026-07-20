"""Vendors API routes (Phase 2C Step 4).

The five /api/vendors handlers were moved verbatim from app.main -- identical
paths, methods, response models, dependencies, store calls, and
exception-to-status mapping. Mounted on a bare APIRouter (no prefix, no tags)
so the public routes and OpenAPI contract are unchanged. app.main includes
this router and re-exports the handler functions, so the tests that call
main.create_vendor_record(...) etc. directly keep working. Uses only the
shared app/api/deps.py aliases (owner-only CRUD with no per-group setup), so
no vendor-specific dependency module is introduced. Vendor-to-part
relationships live entirely in the stores and are untouched.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSessionDep, OwnerAuthContextDep, SettingsDep
from app.models import (
    VendorArchiveResponse,
    VendorCreate,
    VendorListResponse,
    VendorRead,
    VendorUpdate,
)
from app.vendor_store import (
    VendorNotFoundError,
    VendorStoreError,
    archive_vendor,
    create_vendor,
    get_vendor,
    list_vendors,
    update_vendor,
)

logger = logging.getLogger("optimus")

router = APIRouter()


@router.post("/api/vendors", response_model=VendorRead)
async def create_vendor_record(
    payload: VendorCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> VendorRead:
    try:
        return await asyncio.to_thread(create_vendor, db=db, auth=auth, payload=payload)
    except VendorStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Vendor creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vendor storage is unavailable.",
        ) from exc


@router.get("/api/vendors", response_model=VendorListResponse)
async def list_vendor_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    search: str | None = Query(default=None, max_length=120),
    archived: bool = False,
) -> VendorListResponse:
    try:
        return await asyncio.to_thread(
            list_vendors,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            archived=archived,
            search=search,
        )
    except VendorStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Vendor listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vendor storage is unavailable.",
        ) from exc


@router.get("/api/vendors/{vendor_id}", response_model=VendorRead)
async def get_vendor_record(
    vendor_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> VendorRead:
    try:
        return await asyncio.to_thread(get_vendor, db=db, auth=auth, vendor_id=vendor_id)
    except VendorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VendorStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Vendor retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vendor storage is unavailable.",
        ) from exc


@router.patch("/api/vendors/{vendor_id}", response_model=VendorRead)
async def update_vendor_record(
    vendor_id: int,
    payload: VendorUpdate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> VendorRead:
    try:
        return await asyncio.to_thread(
            update_vendor, db=db, auth=auth, vendor_id=vendor_id, payload=payload
        )
    except VendorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VendorStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Vendor update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vendor storage is unavailable.",
        ) from exc


@router.delete("/api/vendors/{vendor_id}", response_model=VendorArchiveResponse)
async def archive_vendor_record(
    vendor_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> VendorArchiveResponse:
    try:
        return await asyncio.to_thread(archive_vendor, db=db, auth=auth, vendor_id=vendor_id)
    except VendorNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VendorStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Vendor archive failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vendor storage is unavailable.",
        ) from exc
