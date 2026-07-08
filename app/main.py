from __future__ import annotations

import asyncio
import logging
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.auth import (
    AuthContext,
    authenticate_user,
    clear_session_cookie,
    create_auth_session,
    get_current_auth_context,
    require_authenticated_user,
    set_session_cookie,
)
from app.config import Settings, get_settings
from app.context_store import (
    ContextCapacityError,
    ContextConflictError,
    ContextStoreError,
    delete_entry,
    list_entries,
    upsert_entry,
)
from app.customer_store import (
    CustomerNotFoundError,
    CustomerStoreError,
    archive_customer,
    create_customer,
    get_customer,
    list_customers,
    update_customer,
)
from app.db import get_db_session
from app.db_models import UserAccount
from app.errors import EstimatorResearchError
from app.estimate_store import (
    EstimateApprovalTokenError,
    EstimateNotFoundError,
    EstimateStoreError,
    approval_history,
    approve_estimate,
    create_estimate,
    create_estimate_revision,
    decline_estimate,
    get_approval_view,
    get_estimate,
    list_estimates,
    send_estimate_for_approval,
    update_estimate,
)
from app.models import (
    AuthLoginRequest,
    AuthMeResponse,
    AuthSessionResponse,
    AuthUser,
    ChatRequest,
    ChatResponse,
    ContextDeleteResponse,
    ContextEntryRead,
    ContextEntryUpsertRequest,
    ContextListResponse,
    ContextScope,
    CustomerArchiveResponse,
    CustomerCreate,
    CustomerListResponse,
    CustomerRead,
    CustomerUpdate,
    EstimateApprovalActionRequest,
    EstimateApprovalActionResponse,
    EstimateApprovalAuditResponse,
    EstimateApprovalPublicView,
    EstimateApprovalSendResponse,
    EstimateApprovalTokenRequest,
    EstimateCreate,
    EstimateDeclineActionRequest,
    EstimateListResponse,
    EstimateRead,
    EstimateRequest,
    EstimateResponse,
    EstimateRevisionCreate,
    EstimateSendForApprovalRequest,
    EstimateStatus,
    EstimateUpdate,
    LocationInput,
    ResolvedLocation,
    VehicleArchiveResponse,
    VehicleCreate,
    VehicleListResponse,
    VehicleRead,
    VehicleUpdate,
    WorkOrderListResponse,
    WorkOrderNoteCreate,
    WorkOrderRead,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
    WorkOrderUpdate,
)
from app.orchestrator import OptimusResearchOrchestrator
from app.rate_limit import RateLimitExceeded, SlidingWindowRateLimiter
from app.services.http import SafeHttpClient
from app.services.location import LocationService
from app.services.optimus_chat import OptimusChatService
from app.vehicle_store import (
    VehicleNotFoundError,
    VehicleStoreError,
    archive_vehicle,
    create_vehicle,
    get_vehicle,
    list_vehicles,
    update_vehicle,
)
from app.work_order_store import (
    WorkOrderNotFoundError,
    WorkOrderStoreError,
    add_work_order_note,
    create_work_order_from_estimate,
    get_work_order,
    list_work_orders,
    transition_work_order_status,
    update_work_order,
)

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger("optimus")
STATIC_DIR = Path(__file__).parent / "static"
SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[Session, Depends(get_db_session)]
AuthContextDep = Annotated[AuthContext, Depends(get_current_auth_context)]
CurrentUserDep = Annotated[UserAccount, Depends(require_authenticated_user)]

app = FastAPI(
    title="Optimus Command Center | Landon Motor Works",
    version=__version__,
    docs_url="/docs",
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=("http://127.0.0.1:5173", "http://localhost:5173"),
    allow_credentials=True,
    allow_methods=("GET", "POST", "OPTIONS"),
    allow_headers=("Content-Type",),
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
_rate_limiter: SlidingWindowRateLimiter | None = None


def get_rate_limiter(settings: Settings) -> SlidingWindowRateLimiter:
    global _rate_limiter
    if _rate_limiter is None or _rate_limiter.limit != settings.max_estimates_per_minute:
        _rate_limiter = SlidingWindowRateLimiter(limit=settings.max_estimates_per_minute)
    return _rate_limiter


async def enforce_rate_limit(request: Request, settings: Settings) -> None:
    client_host = request.client.host if request.client else "unknown"
    client_key = f"{request.url.path}:{client_host}"
    try:
        await get_rate_limiter(settings).check(client_key)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


def location_service(settings: Settings) -> LocationService:
    http = SafeHttpClient(
        timeout_seconds=settings.http_timeout_seconds,
        allowed_hosts=("geocoding.geo.census.gov",),
    )
    return LocationService(http)


@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(self)"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'"
    )
    return response


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
async def login_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/approval", include_in_schema=False)
async def approval_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health(settings: SettingsDep) -> dict[str, str | bool]:
    return {
        "status": "ok",
        "version": __version__,
        "business_name": settings.business_name,
        "business_tagline": settings.business_tagline,
        "web_search_configured": bool(settings.openai_api_key),
        "owner_full_control": settings.autonomy_mode == "owner_full_control",
        "direct_owner_chat_default": settings.direct_owner_chat_default,
        "agent_delegation_enabled": settings.agent_delegation_enabled,
        "estimator_model": settings.estimator_model,
        "estimator_fallback_model": settings.openai_fallback_model,
        "auth_configured": bool(
            settings.optimus_owner_username and settings.optimus_owner_password
        ),
    }


def _tcp_dependency_ready(url: str, default_port: int, timeout_seconds: float = 1.0) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    port = parsed.port or default_port
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


@app.get("/ready")
async def ready(settings: SettingsDep) -> dict[str, object]:
    postgres_ready = _tcp_dependency_ready(settings.database_url, 5432)
    redis_ready = _tcp_dependency_ready(settings.redis_url, 6379)
    ready_status = postgres_ready and redis_ready
    return {
        "status": "ready" if ready_status else "degraded",
        "version": __version__,
        "dependencies": {
            "postgres": postgres_ready,
            "redis": redis_ready,
        },
    }


def auth_user_response(user: Any) -> AuthUser:
    return AuthUser.model_validate(user)


def ensure_context_dependencies(settings: Settings) -> None:
    if settings.app_env == "test":
        return
    unavailable: list[str] = []
    if not _tcp_dependency_ready(settings.database_url, 5432):
        unavailable.append("postgres")
    if not _tcp_dependency_ready(settings.redis_url, 6379):
        unavailable.append("redis")
    if unavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "context_dependencies_unavailable",
                "message": "Context management dependencies are unavailable.",
                "unavailable_dependencies": unavailable,
            },
        )


@app.post("/api/auth/login", response_model=AuthSessionResponse)
async def login(
    payload: AuthLoginRequest,
    request: Request,
    response: Response,
    db: DbSessionDep,
    settings: SettingsDep,
) -> AuthSessionResponse:
    user = authenticate_user(db=db, username=payload.username, password=payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password."
        )

    session_token, auth_session = create_auth_session(
        db=db, settings=settings, user=user, request=request
    )
    set_session_cookie(response, settings, session_token, auth_session.expires_at)
    return AuthSessionResponse(
        user=auth_user_response(user),
        expires_at=auth_session.expires_at,
        session_expires_in_seconds=settings.session_ttl_hours * 3600,
    )


@app.post("/api/auth/logout")
async def logout(
    response: Response,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
) -> dict[str, bool]:
    auth.session.revoked_at = auth.session.revoked_at or datetime.now(UTC)
    db.add(auth.session)
    db.commit()
    clear_session_cookie(response, settings)
    return {"ok": True}


@app.get("/api/auth/me", response_model=AuthMeResponse)
async def auth_me(auth: AuthContextDep) -> AuthMeResponse:
    return AuthMeResponse(
        user=auth_user_response(auth.user),
        expires_at=auth.session.expires_at,
    )


@app.post("/api/customers", response_model=CustomerRead)
async def create_customer_record(
    payload: CustomerCreate,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> CustomerRead:
    try:
        return create_customer(db=db, auth=auth, payload=payload)
    except CustomerStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Customer creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Customer storage is unavailable.",
        ) from exc


@app.get("/api/customers", response_model=CustomerListResponse)
async def list_customer_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    search: str | None = Query(default=None, max_length=120),
    archived: bool = False,
) -> CustomerListResponse:
    try:
        return list_customers(
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            archived=archived,
            search=search,
        )
    except CustomerStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Customer listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Customer storage is unavailable.",
        ) from exc


@app.get("/api/customers/{customer_id}", response_model=CustomerRead)
async def get_customer_record(
    customer_id: int,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> CustomerRead:
    try:
        return get_customer(db=db, auth=auth, customer_id=customer_id)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Customer retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Customer storage is unavailable.",
        ) from exc


@app.patch("/api/customers/{customer_id}", response_model=CustomerRead)
async def update_customer_record(
    customer_id: int,
    payload: CustomerUpdate,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> CustomerRead:
    try:
        return update_customer(db=db, auth=auth, customer_id=customer_id, payload=payload)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Customer update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Customer storage is unavailable.",
        ) from exc


@app.delete("/api/customers/{customer_id}", response_model=CustomerArchiveResponse)
async def archive_customer_record(
    customer_id: int,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> CustomerArchiveResponse:
    try:
        return archive_customer(db=db, auth=auth, customer_id=customer_id)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Customer archive failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Customer storage is unavailable.",
        ) from exc


@app.post("/api/customers/{customer_id}/vehicles", response_model=VehicleRead)
async def create_vehicle_record(
    customer_id: int,
    payload: VehicleCreate,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> VehicleRead:
    try:
        return create_vehicle(db=db, auth=auth, customer_id=customer_id, payload=payload)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VehicleStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Vehicle creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vehicle storage is unavailable.",
        ) from exc


@app.get("/api/customers/{customer_id}/vehicles", response_model=VehicleListResponse)
async def list_customer_vehicle_records(
    customer_id: int,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    search: str | None = Query(default=None, max_length=120),
    archived: bool = False,
) -> VehicleListResponse:
    try:
        return list_vehicles(
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            archived=archived,
            search=search,
            customer_id=customer_id,
        )
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VehicleStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Customer vehicle listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vehicle storage is unavailable.",
        ) from exc


@app.get("/api/vehicles", response_model=VehicleListResponse)
async def list_vehicle_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    search: str | None = Query(default=None, max_length=120),
    customer_id: int | None = Query(default=None, ge=1),
    archived: bool = False,
) -> VehicleListResponse:
    try:
        return list_vehicles(
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            archived=archived,
            search=search,
            customer_id=customer_id,
        )
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VehicleStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Vehicle listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vehicle storage is unavailable.",
        ) from exc


@app.get("/api/vehicles/{vehicle_id}", response_model=VehicleRead)
async def get_vehicle_record(
    vehicle_id: int,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> VehicleRead:
    try:
        return get_vehicle(db=db, auth=auth, vehicle_id=vehicle_id)
    except VehicleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VehicleStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Vehicle retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vehicle storage is unavailable.",
        ) from exc


@app.patch("/api/vehicles/{vehicle_id}", response_model=VehicleRead)
async def update_vehicle_record(
    vehicle_id: int,
    payload: VehicleUpdate,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> VehicleRead:
    try:
        return update_vehicle(db=db, auth=auth, vehicle_id=vehicle_id, payload=payload)
    except VehicleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VehicleStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Vehicle update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vehicle storage is unavailable.",
        ) from exc


@app.delete("/api/vehicles/{vehicle_id}", response_model=VehicleArchiveResponse)
async def archive_vehicle_record(
    vehicle_id: int,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> VehicleArchiveResponse:
    try:
        return archive_vehicle(db=db, auth=auth, vehicle_id=vehicle_id)
    except VehicleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VehicleStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Vehicle archive failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vehicle storage is unavailable.",
        ) from exc


@app.get("/api/context/{project_key}", response_model=ContextListResponse)
async def get_context(
    project_key: str,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
    scope: ContextScope = ContextScope.PROJECT,
) -> ContextListResponse:
    ensure_context_dependencies(settings)
    try:
        return list_entries(
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


@app.put("/api/context/{project_key}/{context_key}", response_model=ContextEntryRead)
async def put_context(
    project_key: str,
    context_key: str,
    payload: ContextEntryUpsertRequest,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
    scope: ContextScope = ContextScope.PROJECT,
) -> ContextEntryRead:
    ensure_context_dependencies(settings)
    try:
        return upsert_entry(
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


@app.delete("/api/context/{project_key}/{context_key}", response_model=ContextDeleteResponse)
async def remove_context(
    project_key: str,
    context_key: str,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
    scope: ContextScope = ContextScope.PROJECT,
    expected_revision: int | None = None,
) -> ContextDeleteResponse:
    ensure_context_dependencies(settings)
    try:
        return delete_entry(
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


@app.post(
    "/api/location/resolve",
    response_model=ResolvedLocation,
)
async def resolve_location(
    location: LocationInput,
    settings: SettingsDep,
    current_user: CurrentUserDep,
) -> ResolvedLocation:
    del current_user
    return await location_service(settings).resolve(location)


@app.post(
    "/api/chat",
    response_model=ChatResponse,
)
async def chat(
    payload: ChatRequest,
    request_context: Request,
    settings: SettingsDep,
    current_user: CurrentUserDep,
) -> ChatResponse:
    del current_user
    await enforce_rate_limit(request_context, settings)
    if len(payload.message) > settings.max_chat_text_length:
        raise HTTPException(status_code=422, detail="Message is too long.")
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")

    try:
        resolved_location = (
            await location_service(settings).resolve(payload.location) if payload.location else None
        )
        service = OptimusChatService(settings)
        return await asyncio.to_thread(
            service.respond,
            request=payload,
            location=resolved_location,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning("Optimus chat failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected Optimus chat failure")
        raise HTTPException(status_code=502, detail="Optimus chat failed.") from exc


@app.post(
    "/api/estimate",
    response_model=EstimateResponse,
)
async def estimate(
    request: EstimateRequest,
    request_context: Request,
    settings: SettingsDep,
    current_user: CurrentUserDep,
) -> EstimateResponse:
    del current_user
    await enforce_rate_limit(request_context, settings)

    if len(request.job) > settings.max_job_text_length:
        raise HTTPException(status_code=422, detail="Job description is too long.")
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")

    try:
        orchestrator = OptimusResearchOrchestrator(settings)
        return await orchestrator.estimate_job(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EstimatorResearchError as exc:
        logger.warning(
            "Estimate research failed request_id=%s stage=%s code=%s",
            exc.request_id,
            exc.stage,
            exc.code,
        )
        raise HTTPException(status_code=exc.http_status, detail=exc.as_detail()) from exc
    except RuntimeError as exc:
        logger.warning("Estimate research failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected estimate failure")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "unexpected_estimator_failure",
                "message": "The estimator failed unexpectedly. Run DIAGNOSE_ESTIMATOR.bat.",
                "stage": "estimate_pipeline",
                "request_id": "not-available",
            },
        ) from exc


@app.post("/api/estimates", response_model=EstimateRead)
async def create_estimate_record(
    payload: EstimateCreate,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
) -> EstimateRead:
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")
    try:
        return await create_estimate(
            db=db,
            auth=auth,
            payload=payload,
            orchestrator=OptimusResearchOrchestrator(settings),
        )
    except (CustomerStoreError, VehicleStoreError, EstimateStoreError) as exc:
        status_code_value = (
            404
            if isinstance(exc, (CustomerNotFoundError, VehicleNotFoundError, EstimateNotFoundError))
            else 422
        )
        raise HTTPException(status_code=status_code_value, detail=str(exc)) from exc
    except EstimatorResearchError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.as_detail()) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Estimate storage is unavailable.",
        ) from exc


@app.get("/api/estimates", response_model=EstimateListResponse)
async def list_estimate_records(
    db: DbSessionDep,
    auth: AuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    status_filter: Annotated[EstimateStatus | None, Query(alias="status")] = None,
    search: str | None = Query(default=None, max_length=120),
    customer_id: int | None = Query(default=None, ge=1),
    vehicle_id: int | None = Query(default=None, ge=1),
    archived: bool = False,
) -> EstimateListResponse:
    try:
        return list_estimates(
            db=db,
            auth=auth,
            page=page,
            page_size=page_size,
            status=status_filter,
            search=search,
            customer_id=customer_id,
            vehicle_id=vehicle_id,
            archived=archived,
        )
    except (CustomerStoreError, VehicleStoreError, EstimateStoreError) as exc:
        status_code_value = (
            404
            if isinstance(exc, (CustomerNotFoundError, VehicleNotFoundError, EstimateNotFoundError))
            else 422
        )
        raise HTTPException(status_code=status_code_value, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Estimate storage is unavailable.",
        ) from exc


@app.get("/api/estimates/{estimate_id}", response_model=EstimateRead)
async def get_estimate_record(
    estimate_id: int,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> EstimateRead:
    try:
        return get_estimate(db=db, auth=auth, estimate_id=estimate_id)
    except EstimateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EstimateStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Estimate storage is unavailable.",
        ) from exc


@app.patch("/api/estimates/{estimate_id}", response_model=EstimateRead)
async def update_estimate_record(
    estimate_id: int,
    payload: EstimateUpdate,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> EstimateRead:
    try:
        return update_estimate(db=db, auth=auth, estimate_id=estimate_id, payload=payload)
    except EstimateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EstimateStoreError as exc:
        raise HTTPException(
            status_code=409 if "locked" in str(exc).lower() else 422, detail=str(exc)
        ) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Estimate storage is unavailable.",
        ) from exc


@app.post("/api/estimates/{estimate_id}/create-revision", response_model=EstimateRead)
async def create_estimate_revision_record(
    estimate_id: int,
    payload: EstimateRevisionCreate,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
) -> EstimateRead:
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")
    try:
        return await create_estimate_revision(
            db=db,
            auth=auth,
            estimate_id=estimate_id,
            payload=payload,
            orchestrator=OptimusResearchOrchestrator(settings),
        )
    except (CustomerStoreError, VehicleStoreError, EstimateStoreError) as exc:
        status_code_value = (
            404
            if isinstance(exc, (CustomerNotFoundError, VehicleNotFoundError, EstimateNotFoundError))
            else 422
        )
        raise HTTPException(status_code=status_code_value, detail=str(exc)) from exc
    except EstimatorResearchError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.as_detail()) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate revision creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Estimate storage is unavailable.",
        ) from exc


@app.post(
    "/api/estimates/{estimate_id}/send-for-approval", response_model=EstimateApprovalSendResponse
)
async def send_estimate_record_for_approval(
    estimate_id: int,
    payload: EstimateSendForApprovalRequest,
    db: DbSessionDep,
    auth: AuthContextDep,
    request_context: Request,
) -> EstimateApprovalSendResponse:
    del request_context
    try:
        return send_estimate_for_approval(
            db=db,
            auth=auth,
            estimate_id=estimate_id,
            payload=payload,
            approval_base_url="/approval",
        )
    except EstimateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EstimateStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate send-for-approval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Estimate storage is unavailable.",
        ) from exc


@app.post("/api/estimate-approval/view", response_model=EstimateApprovalPublicView)
async def approval_view(
    payload: EstimateApprovalTokenRequest,
    db: DbSessionDep,
    request_context: Request,
    settings: SettingsDep,
) -> EstimateApprovalPublicView:
    await enforce_rate_limit(request_context, settings)
    try:
        return get_approval_view(db=db, payload=payload)
    except EstimateApprovalTokenError as exc:
        raise HTTPException(
            status_code=404,
            detail="Approval token is invalid or unavailable.",
        ) from exc
    except EstimateStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate approval view failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Estimate storage is unavailable.",
        ) from exc


@app.post("/api/estimate-approval/approve", response_model=EstimateApprovalActionResponse)
async def approval_approve(
    payload: EstimateApprovalActionRequest,
    db: DbSessionDep,
    request_context: Request,
    settings: SettingsDep,
) -> EstimateApprovalActionResponse:
    await enforce_rate_limit(request_context, settings)
    try:
        return approve_estimate(
            db=db,
            payload=payload,
            ip_address=request_context.client.host if request_context.client else None,
            user_agent=request_context.headers.get("user-agent"),
        )
    except EstimateApprovalTokenError as exc:
        raise HTTPException(
            status_code=404,
            detail="Approval token is invalid or unavailable.",
        ) from exc
    except EstimateStoreError as exc:
        detail = str(exc)
        status_code_value = (
            409 if "mismatch" in detail.lower() or "expired" in detail.lower() else 422
        )
        raise HTTPException(status_code=status_code_value, detail=detail) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate approval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Estimate storage is unavailable.",
        ) from exc


@app.post("/api/estimate-approval/decline", response_model=EstimateApprovalActionResponse)
async def approval_decline(
    payload: EstimateDeclineActionRequest,
    db: DbSessionDep,
    request_context: Request,
    settings: SettingsDep,
) -> EstimateApprovalActionResponse:
    await enforce_rate_limit(request_context, settings)
    try:
        return decline_estimate(
            db=db,
            payload=payload,
            ip_address=request_context.client.host if request_context.client else None,
            user_agent=request_context.headers.get("user-agent"),
        )
    except EstimateApprovalTokenError as exc:
        raise HTTPException(
            status_code=404,
            detail="Approval token is invalid or unavailable.",
        ) from exc
    except EstimateStoreError as exc:
        detail = str(exc)
        status_code_value = (
            409 if "mismatch" in detail.lower() or "expired" in detail.lower() else 422
        )
        raise HTTPException(status_code=status_code_value, detail=detail) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate decline failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Estimate storage is unavailable.",
        ) from exc


@app.get(
    "/api/estimates/{estimate_id}/approval-history", response_model=EstimateApprovalAuditResponse
)
async def estimate_approval_history(
    estimate_id: int,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> EstimateApprovalAuditResponse:
    try:
        return approval_history(db=db, auth=auth, estimate_id=estimate_id)
    except EstimateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EstimateStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate approval history failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Estimate storage is unavailable.",
        ) from exc


@app.post("/api/estimates/{estimate_id}/work-order", response_model=WorkOrderRead)
async def create_work_order_record(
    estimate_id: int,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> WorkOrderRead:
    try:
        return create_work_order_from_estimate(db=db, auth=auth, estimate_id=estimate_id)
    except EstimateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (EstimateStoreError, WorkOrderStoreError) as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=409 if "not implemented" in detail.lower() else 422,
            detail=detail,
        ) from exc
    except SQLAlchemyError as exc:
        logger.warning("Work-order conversion failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Work-order storage is unavailable.",
        ) from exc


@app.get("/api/work-orders", response_model=WorkOrderListResponse)
async def list_work_order_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    status_filter: Annotated[WorkOrderStatus | None, Query(alias="status")] = None,
    search: str | None = Query(default=None, max_length=120),
    customer_id: int | None = Query(default=None, ge=1),
    vehicle_id: int | None = Query(default=None, ge=1),
) -> WorkOrderListResponse:
    try:
        return list_work_orders(
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            status=status_filter,
            search=search,
            customer_id=customer_id,
            vehicle_id=vehicle_id,
        )
    except WorkOrderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Work-order listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Work-order storage is unavailable.",
        ) from exc


@app.get("/api/work-orders/{work_order_id}", response_model=WorkOrderRead)
async def get_work_order_record(
    work_order_id: int,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> WorkOrderRead:
    try:
        return get_work_order(db=db, auth=auth, work_order_id=work_order_id)
    except WorkOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkOrderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Work-order retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Work-order storage is unavailable.",
        ) from exc


@app.patch("/api/work-orders/{work_order_id}", response_model=WorkOrderRead)
async def update_work_order_record(
    work_order_id: int,
    payload: WorkOrderUpdate,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> WorkOrderRead:
    try:
        return update_work_order(db=db, auth=auth, work_order_id=work_order_id, payload=payload)
    except WorkOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkOrderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Work-order update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Work-order storage is unavailable.",
        ) from exc


@app.post("/api/work-orders/{work_order_id}/status", response_model=WorkOrderRead)
async def update_work_order_status_record(
    work_order_id: int,
    payload: WorkOrderStatusUpdate,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> WorkOrderRead:
    try:
        return transition_work_order_status(
            db=db,
            auth=auth,
            work_order_id=work_order_id,
            payload=payload,
        )
    except WorkOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkOrderStoreError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=409 if "cannot transition" in detail.lower() else 422,
            detail=detail,
        ) from exc
    except SQLAlchemyError as exc:
        logger.warning("Work-order status update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Work-order storage is unavailable.",
        ) from exc


@app.post("/api/work-orders/{work_order_id}/notes", response_model=WorkOrderRead)
async def add_work_order_note_record(
    work_order_id: int,
    payload: WorkOrderNoteCreate,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> WorkOrderRead:
    try:
        return add_work_order_note(db=db, auth=auth, work_order_id=work_order_id, payload=payload)
    except WorkOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkOrderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Work-order note creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Work-order storage is unavailable.",
        ) from exc
