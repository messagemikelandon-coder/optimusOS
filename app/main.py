from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import socket
from datetime import UTC, datetime, timedelta
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
from app.account_security_store import (
    InvitationConflictError,
    InvitationError,
    MemberManagementError,
    PasswordChangeError,
    PasswordResetTokenError,
    SessionNotFoundError,
    accept_invitation,
    authenticate_account,
    change_password,
    confirm_password_reset,
    create_invitation,
    list_invitations,
    list_members,
    list_sessions,
    login_history,
    record_login_success,
    request_password_reset,
    revoke_invitation,
    revoke_other_sessions,
    revoke_session,
    security_summary,
    update_member_status,
)
from app.auth import (
    AuthContext,
    clear_session_cookie,
    create_auth_session,
    get_current_auth_context,
    require_authenticated_user,
    require_billing_context,
    require_owner_context,
    require_owner_or_technician_context,
    require_support_context,
    require_verified_auth_context,
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
from app.customer_history_store import get_customer_history
from app.customer_store import (
    CustomerNotFoundError,
    CustomerStoreError,
    archive_customer,
    create_customer,
    get_customer,
    list_customers,
    update_customer,
)
from app.dashboard_store import get_dashboard_summary
from app.db import get_db_session, get_engine
from app.db_models import UserAccount
from app.diagnostics_store import (
    DiagnosticFindingNotFoundError,
    DiagnosticsStoreError,
    archive_diagnostic_finding,
    create_diagnostic_finding,
    get_diagnostic_finding,
    list_diagnostic_finding_events,
    list_diagnostic_findings,
    update_diagnostic_finding,
)
from app.email_verification_store import (
    EmailVerificationError,
    EmailVerificationTokenError,
    confirm_email_verification,
    request_email_verification,
)
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
    revoke_estimate_approval_request,
    send_estimate_for_approval,
    update_estimate,
)
from app.inspection_store import (
    InspectionNotFoundError,
    InspectionStoreError,
    archive_inspection,
    create_inspection,
    get_inspection,
    list_inspection_events,
    list_inspections,
    update_inspection,
)
from app.intake_store import (
    IntakeConflictError,
    IntakeRequestNotFoundError,
    IntakeStoreError,
    convert_intake_request,
    create_intake_request,
    get_intake_request,
    list_intake_requests,
    update_intake_request,
)
from app.invoice_store import (
    InvoiceNotFoundError,
    InvoiceStoreError,
    get_invoice,
    issue_invoice,
    list_invoices,
    render_invoice_html,
    render_invoice_pdf,
)
from app.migration_compat import (
    SchemaCompatibility,
    check_schema_compatibility,
    get_app_migration_head,
)
from app.models import (
    AccountSecurityRead,
    AccountStatusUpdate,
    AddPaymentMethodRequest,
    AppointmentCancelRequest,
    AppointmentCreate,
    AppointmentListResponse,
    AppointmentMoveRequest,
    AppointmentRead,
    AppointmentStatus,
    AppointmentUpdate,
    AuthLoginHistoryResponse,
    AuthLoginRequest,
    AuthMeResponse,
    AuthSessionListResponse,
    AuthSessionResponse,
    AuthUser,
    AvailabilityResponse,
    BayArchiveResponse,
    BayCreate,
    BayListResponse,
    BayRead,
    BayUpdate,
    ChatRequest,
    ChatResponse,
    ConcurrencyProbeResponse,
    ContextDeleteResponse,
    ContextEntryRead,
    ContextEntryUpsertRequest,
    ContextListResponse,
    ContextScope,
    CustomerArchiveResponse,
    CustomerCreate,
    CustomerHistoryResponse,
    CustomerListResponse,
    CustomerRead,
    CustomerUpdate,
    DashboardSummaryResponse,
    DiagnosticFindingArchiveResponse,
    DiagnosticFindingCreate,
    DiagnosticFindingEventsResponse,
    DiagnosticFindingListResponse,
    DiagnosticFindingRead,
    DiagnosticFindingUpdate,
    DiagnosticInspectionReportResponse,
    EstimateApprovalActionRequest,
    EstimateApprovalActionResponse,
    EstimateApprovalAuditResponse,
    EstimateApprovalPublicView,
    EstimateApprovalRevokeRequest,
    EstimateApprovalSendResponse,
    EstimateApprovalTokenRequest,
    EstimateCreate,
    EstimateDeclineActionRequest,
    EstimateListResponse,
    EstimateRead,
    EstimateRevisionCreate,
    EstimateSendForApprovalRequest,
    EstimateStatus,
    EstimateUpdate,
    InspectionArchiveResponse,
    InspectionCreate,
    InspectionEventsResponse,
    InspectionListResponse,
    InspectionRead,
    InspectionUpdate,
    IntakeRequestConvertRequest,
    IntakeRequestConvertResponse,
    IntakeRequestCreate,
    IntakeRequestListResponse,
    IntakeRequestRead,
    IntakeRequestUpdate,
    InventoryValuationReportResponse,
    InvoiceIssueRequest,
    InvoiceListResponse,
    InvoicePaymentCreate,
    InvoicePaymentVoidRequest,
    InvoiceRead,
    InvoiceStatus,
    LocationInput,
    NotificationListResponse,
    NotificationMarkReadResponse,
    PartAllocationAllocateRequest,
    PartAllocationCreate,
    PartAllocationEventsResponse,
    PartAllocationListResponse,
    PartAllocationRead,
    PartAllocationReturnRequest,
    PartAllocationTechnicianRead,
    PartAllocationUseRequest,
    PartArchiveResponse,
    PartCreate,
    PartListResponse,
    PartRead,
    PartsUsageReportResponse,
    PartUpdate,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PaymentActivityReportResponse,
    PurchaseOrderCreate,
    PurchaseOrderListResponse,
    PurchaseOrderRead,
    PurchaseOrderReceiptsResponse,
    PurchaseOrderReceiveRequest,
    PurchaseOrderStatus,
    ResolvedLocation,
    ScheduleBlockCreate,
    ScheduleBlockListResponse,
    ScheduleBlockRead,
    ScheduleBlockUpdate,
    ShopInvitationAccept,
    ShopInvitationAcceptResponse,
    ShopInvitationCreate,
    ShopInvitationRead,
    ShopMemberRead,
    ShopSignupRequest,
    SubscribeRequest,
    SubscriptionEventsResponse,
    SubscriptionRead,
    SupportShopListResponse,
    SyntheticAccountResponse,
    SyntheticCleanupResponse,
    SyntheticTechnicianRequest,
    TechnicianArchiveResponse,
    TechnicianClockResponse,
    TechnicianCreate,
    TechnicianListResponse,
    TechnicianMeResponse,
    TechnicianProvisionLoginRequest,
    TechnicianProvisionLoginResponse,
    TechnicianRead,
    TechnicianTimeReportResponse,
    TechnicianUpdate,
    VehicleArchiveResponse,
    VehicleCreate,
    VehicleListResponse,
    VehicleRead,
    VehicleUpdate,
    VendorArchiveResponse,
    VendorCreate,
    VendorListResponse,
    VendorPurchasingReportResponse,
    VendorRead,
    VendorUpdate,
    VerifyEmailRequest,
    WorkflowGapCreate,
    WorkflowGapEventsResponse,
    WorkflowGapListResponse,
    WorkflowGapRead,
    WorkflowGapSeverity,
    WorkflowGapStatus,
    WorkflowGapUpdate,
    WorkingHoursCreate,
    WorkingHoursListResponse,
    WorkingHoursRead,
    WorkingHoursUpdate,
    WorkOrderAssignTechnicianRequest,
    WorkOrderCycleTimeReportResponse,
    WorkOrderListResponse,
    WorkOrderNoteCreate,
    WorkOrderRead,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
    WorkOrderUpdate,
)
from app.notification_store import (
    NotificationNotFoundError,
    NotificationStoreError,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
from app.observability import configure_structured_logging, install_request_context_middleware
from app.orchestrator import OptimusResearchOrchestrator
from app.part_allocation_store import (
    PartAllocationNotFoundError,
    PartAllocationStoreError,
    allocate_part,
    create_part_allocation,
    get_part_allocation,
    list_part_allocation_events,
    list_part_allocations,
    return_part_allocation,
    use_part_allocation,
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
from app.payment_store import PaymentNotFoundError, record_payment, void_payment
from app.purchase_order_store import (
    PurchaseOrderNotFoundError,
    PurchaseOrderStoreError,
    cancel_purchase_order,
    create_purchase_order,
    get_purchase_order,
    list_purchase_order_receipts,
    list_purchase_orders,
    receive_purchase_order_line_item,
    submit_purchase_order,
)
from app.rate_limit import RateLimiter, RateLimiterRegistry, RateLimitExceeded
from app.report_store import (
    get_diagnostic_inspection_report,
    get_inventory_valuation_report,
    get_parts_usage_report,
    get_payment_activity_report,
    get_technician_time_report,
    get_vendor_purchasing_report,
    get_work_order_cycle_time_report,
)
from app.scheduling_store import (
    SchedulingConflictError,
    SchedulingNotFoundError,
    SchedulingStoreError,
    archive_bay,
    cancel_appointment,
    create_appointment,
    create_bay,
    create_schedule_block,
    create_working_hours,
    delete_schedule_block,
    delete_working_hours,
    get_appointment,
    get_availability,
    get_bay,
    get_schedule_block,
    list_appointments,
    list_bays,
    list_schedule_blocks,
    list_working_hours,
    move_appointment,
    update_appointment,
    update_bay,
    update_schedule_block,
    update_working_hours,
)
from app.security_events import ActorType, SecurityEventType, log_security_event
from app.services.email import LoggingEmailAdapter
from app.services.http import SafeHttpClient
from app.services.location import LocationService
from app.services.optimus_chat import OptimusChatService
from app.services.square import SquareApiError, SquareInvoiceClient, SquareSubscriptionClient
from app.shop_store import ShopSignupConflictError, ShopSignupError, signup_shop_owner
from app.square_store import (
    SquareAlreadyPushedError,
    SquareStoreError,
    push_invoice_to_square,
    refresh_square_invoice,
)
from app.startup_checks import validate_production_config
from app.subscription_store import (
    SubscriptionConflictError,
    SubscriptionStoreError,
    add_payment_method,
    cancel_subscription,
    change_tier,
    get_subscription,
    list_subscription_events,
    refresh_subscription_from_square,
)
from app.subscription_store import subscribe as subscribe_shop
from app.support_store import (
    SupportNotFoundError,
    end_shop_impersonation,
    impersonate_shop_owner,
    list_shops_for_support,
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
from app.test_support_store import (
    SyntheticOwnerNotFoundError,
    TestSupportDisabledError,
    TestSupportError,
    cleanup_all_synthetic_accounts,
    cleanup_synthetic_account,
    concurrency_probe,
    provision_synthetic_owner,
    provision_synthetic_technician,
    provisioning_enabled,
    reset_concurrency_probe,
)
from app.vehicle_store import (
    VehicleNotFoundError,
    VehicleStoreError,
    archive_vehicle,
    create_vehicle,
    get_vehicle,
    list_vehicles,
    update_vehicle,
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
from app.work_order_store import (
    WorkOrderNotFoundError,
    WorkOrderStoreError,
    add_work_order_note,
    assign_technician,
    create_work_order_from_estimate,
    get_work_order,
    list_work_orders,
    transition_work_order_status,
    update_work_order,
)
from app.workflow_gap_store import (
    WorkflowGapConflictError,
    WorkflowGapNotFoundError,
    WorkflowGapStoreError,
    create_workflow_gap,
    get_workflow_gap,
    list_workflow_gap_events,
    list_workflow_gaps,
    record_workflow_gap_occurrence,
    update_workflow_gap,
)

configure_structured_logging(get_settings().log_level)
logger = logging.getLogger("optimus")
# Fail loudly at import time (i.e. before uvicorn ever accepts a request)
# rather than silently serving traffic on unsafe production configuration.
# See app/startup_checks.py and docs/architecture/adr/ADR-018-environment-database-validation.md.
validate_production_config(get_settings())
STATIC_DIR = Path(__file__).parent / "static"
# Set at image build time (see Dockerfile's GIT_COMMIT build arg); "unknown"
# for a local `uv run uvicorn` dev process that didn't go through a build.
_GIT_COMMIT = os.environ.get("GIT_COMMIT", "unknown")
_APP_MIGRATION_HEAD = get_app_migration_head()
SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[Session, Depends(get_db_session)]
AuthContextDep = Annotated[AuthContext, Depends(get_current_auth_context)]
VerifiedAuthContextDep = Annotated[AuthContext, Depends(require_verified_auth_context)]
CurrentUserDep = Annotated[UserAccount, Depends(require_authenticated_user)]
OwnerAuthContextDep = Annotated[AuthContext, Depends(require_owner_context)]
OwnerOrTechnicianAuthContextDep = Annotated[
    AuthContext, Depends(require_owner_or_technician_context)
]
BillingAuthContextDep = Annotated[AuthContext, Depends(require_billing_context)]
SupportAuthContextDep = Annotated[AuthContext, Depends(require_support_context)]

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
install_request_context_middleware(app, logger)
# All seven rate limiters share one registry (app/rate_limit.py) instead of
# the seven copy-pasted lazy-singleton blocks this used to be. Each concern
# below keeps its own limit, window, per-request key format, and client-facing
# 429 message -- those genuinely differ and must not be homogenized -- while
# the identical wiring (build-once, rebuild-on-limit/redis-url-change,
# Redis-backed with an in-process fallback for brief Redis outages) lives in
# exactly one place. The per-concern get_* accessors are kept as named module
# functions because existing tests monkeypatch them by name.
_rate_limiters = RateLimiterRegistry()


def get_rate_limiter(settings: Settings) -> RateLimiter:
    return _rate_limiters.get(
        "general", redis_url=settings.redis_url, limit=settings.max_estimates_per_minute
    )


async def enforce_rate_limit(request: Request, settings: Settings) -> None:
    client_host = request.client.host if request.client else "unknown"
    client_key = f"{request.url.path}:{client_host}"
    try:
        await get_rate_limiter(settings).check(client_key)
    except RateLimitExceeded as exc:
        log_security_event(
            logger, SecurityEventType.RATE_LIMIT_EXCEEDED, request=request, limit_key=client_key
        )
        raise HTTPException(status_code=429, detail=str(exc)) from exc


def get_login_rate_limiter(settings: Settings) -> RateLimiter:
    return _rate_limiters.get(
        "login", redis_url=settings.redis_url, limit=settings.max_login_attempts_per_minute
    )


async def enforce_login_rate_limit(request: Request, settings: Settings) -> None:
    client_host = request.client.host if request.client else "unknown"
    client_key = f"login:{client_host}"
    try:
        await get_login_rate_limiter(settings).check(client_key)
    except RateLimitExceeded as exc:
        log_security_event(
            logger, SecurityEventType.RATE_LIMIT_EXCEEDED, request=request, limit_key=client_key
        )
        raise HTTPException(
            status_code=429, detail="Too many login attempts. Try again shortly."
        ) from exc


def get_signup_rate_limiter(settings: Settings) -> RateLimiter:
    return _rate_limiters.get(
        "signup", redis_url=settings.redis_url, limit=settings.max_signup_attempts_per_minute
    )


async def enforce_signup_rate_limit(request: Request, settings: Settings) -> None:
    client_host = request.client.host if request.client else "unknown"
    client_key = f"signup:{client_host}"
    try:
        await get_signup_rate_limiter(settings).check(client_key)
    except RateLimitExceeded as exc:
        log_security_event(
            logger, SecurityEventType.RATE_LIMIT_EXCEEDED, request=request, limit_key=client_key
        )
        raise HTTPException(
            status_code=429, detail="Too many signup attempts. Try again shortly."
        ) from exc


def email_adapter() -> LoggingEmailAdapter:
    # Non-sending local/test adapter (/goal Phase 5) -- the only email
    # adapter this codebase has; a real provider is future work requiring
    # explicit owner approval (real email is a stop condition).
    return LoggingEmailAdapter()


def get_email_verification_rate_limiter(settings: Settings) -> RateLimiter:
    return _rate_limiters.get(
        "email-verification",
        redis_url=settings.redis_url,
        limit=settings.max_email_verification_attempts_per_minute,
    )


async def enforce_email_verification_rate_limit(request: Request, settings: Settings) -> None:
    client_host = request.client.host if request.client else "unknown"
    client_key = f"email-verification:{client_host}"
    try:
        await get_email_verification_rate_limiter(settings).check(client_key)
    except RateLimitExceeded as exc:
        log_security_event(
            logger, SecurityEventType.RATE_LIMIT_EXCEEDED, request=request, limit_key=client_key
        )
        raise HTTPException(
            status_code=429, detail="Too many verification attempts. Try again shortly."
        ) from exc


def get_email_verification_resend_rate_limiter(settings: Settings) -> RateLimiter:
    # Keyed per authenticated user (not per IP, unlike login/signup) -- this
    # action requires an existing session, so the abuse case is one account
    # spamming its own inbox. Hourly window.
    return _rate_limiters.get(
        "email-verification-resend",
        redis_url=settings.redis_url,
        limit=settings.max_email_verification_resend_attempts_per_hour,
        window_seconds=3600.0,
    )


async def enforce_email_verification_resend_rate_limit(
    request: Request, settings: Settings, user_id: int
) -> None:
    client_key = f"email-verification-resend:{user_id}"
    try:
        await get_email_verification_resend_rate_limiter(settings).check(client_key)
    except RateLimitExceeded as exc:
        log_security_event(
            logger, SecurityEventType.RATE_LIMIT_EXCEEDED, request=request, limit_key=client_key
        )
        raise HTTPException(
            status_code=429, detail="Too many verification emails requested. Try again later."
        ) from exc


def get_password_reset_rate_limiter(settings: Settings) -> RateLimiter:
    return _rate_limiters.get(
        "password-reset",
        redis_url=settings.redis_url,
        limit=settings.max_password_reset_attempts_per_hour,
        window_seconds=3600.0,
    )


async def enforce_password_reset_rate_limit(
    request: Request, settings: Settings, *, action: str
) -> None:
    client_host = request.client.host if request.client else "unknown"
    client_key = f"password-reset-{action}:{client_host}"
    try:
        await get_password_reset_rate_limiter(settings).check(client_key)
    except RateLimitExceeded as exc:
        log_security_event(
            logger, SecurityEventType.RATE_LIMIT_EXCEEDED, request=request, limit_key=client_key
        )
        raise HTTPException(
            status_code=429, detail="Too many password-reset attempts. Try again later."
        ) from exc


def get_invitation_acceptance_rate_limiter(settings: Settings) -> RateLimiter:
    return _rate_limiters.get(
        "invitation-acceptance",
        redis_url=settings.redis_url,
        limit=settings.max_invitation_acceptance_attempts_per_hour,
        window_seconds=3600.0,
    )


async def enforce_invitation_acceptance_rate_limit(request: Request, settings: Settings) -> None:
    client_host = request.client.host if request.client else "unknown"
    client_key = f"invitation-acceptance:{client_host}"
    try:
        await get_invitation_acceptance_rate_limiter(settings).check(client_key)
    except RateLimitExceeded as exc:
        log_security_event(
            logger, SecurityEventType.RATE_LIMIT_EXCEEDED, request=request, limit_key=client_key
        )
        raise HTTPException(
            status_code=429, detail="Too many invitation attempts. Try again later."
        ) from exc


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
    # Only advertise HSTS when the deployed origin is actually HTTPS -- sending
    # it over plain local HTTP would tell browsers to demand HTTPS on a host
    # that can't serve it, matching the same frontend_origin check already
    # used for the Secure cookie flag in app/auth.py. This deliberately does
    # NOT trust a client-supplied X-Forwarded-Proto header instead, since
    # nothing in front of this app today is confirmed to strip/overwrite that
    # header from untrusted clients -- an attacker reaching the app directly
    # could otherwise force a spoofed HSTS response. Revisit once staging's
    # actual TLS-terminating reverse-proxy topology is chosen and confirmed
    # to control that header.
    if get_settings().frontend_origin.lower().startswith("https://"):
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
async def login_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/signup", include_in_schema=False)
async def signup_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/verify-email", include_in_schema=False)
async def verify_email_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/forgot-password", include_in_schema=False)
async def forgot_password_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/reset-password", include_in_schema=False)
async def reset_password_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/accept-invitation", include_in_schema=False)
async def accept_invitation_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/approval", include_in_schema=False)
async def approval_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health(settings: SettingsDep) -> dict[str, str | bool]:
    return {
        "status": "ok",
        "version": __version__,
        "git_commit": _GIT_COMMIT,
        "migration_head": _APP_MIGRATION_HEAD,
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
        "square_configured": settings.square_configured,
        "square_environment": settings.square_environment,
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
    postgres_ready = await asyncio.to_thread(_tcp_dependency_ready, settings.database_url, 5432)
    redis_ready = await asyncio.to_thread(_tcp_dependency_ready, settings.redis_url, 6379)

    schema_compatibility: str = SchemaCompatibility.UNREACHABLE.value
    database_migration_revision: str | None = None
    schema_safe_to_serve = False
    if postgres_ready:
        try:
            report = await asyncio.to_thread(check_schema_compatibility, get_engine(settings))
            schema_compatibility = report.compatibility.value
            database_migration_revision = report.database_migration_revision
            schema_safe_to_serve = report.safe_to_serve
        except SQLAlchemyError:
            logger.warning("Schema compatibility check failed due to a storage error.")

    ready_status = postgres_ready and redis_ready and schema_safe_to_serve
    return {
        "status": "ready" if ready_status else "degraded",
        "version": __version__,
        "git_commit": _GIT_COMMIT,
        "migration_head": _APP_MIGRATION_HEAD,
        "dependencies": {
            "postgres": postgres_ready,
            "redis": redis_ready,
        },
        "database_migration_revision": database_migration_revision,
        "schema_compatibility": schema_compatibility,
    }


def auth_user_response(
    user: Any, *, db: Session | None = None, session: Any | None = None
) -> AuthUser:
    response = AuthUser.model_validate(user)
    if db is not None and session is not None and session.impersonated_by_user_account_id:
        impersonator = db.get(UserAccount, session.impersonated_by_user_account_id)
        response.is_impersonated = True
        response.impersonated_by_username = impersonator.username if impersonator else None
    return response


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
    await enforce_login_rate_limit(request, settings)
    user = authenticate_account(
        db,
        settings,
        request,
        username=payload.username,
        password=payload.password,
    )
    if user is None:
        # Logs a hash, not the raw attempted username: a real user who
        # fat-fingers the login form can end up with their password typed
        # into the username field, and this event fires on every failed
        # attempt. The hash still lets an owner/monitor correlate repeated
        # failures against the same attempted value (e.g. "47 failed
        # attempts against the same username-hash in one minute") without
        # ever persisting a value that could be a leaked password.
        log_security_event(
            logger,
            SecurityEventType.LOGIN_FAILED,
            request=request,
            username_hash=hashlib.sha256(payload.username.encode("utf-8")).hexdigest()[:12],
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password."
        )

    session_token, auth_session = create_auth_session(
        db=db, settings=settings, user=user, request=request
    )
    record_login_success(db, user, auth_session, request)
    set_session_cookie(response, settings, session_token, auth_session.expires_at)
    log_security_event(
        logger,
        SecurityEventType.LOGIN_SUCCEEDED,
        request=request,
        level=logging.INFO,
        # Hashed for the same reason as LOGIN_FAILED above, and for
        # consistency with it -- a plaintext username has no legitimate need
        # to sit in a structured log line when `user_id` already identifies
        # the account precisely.
        username_hash=hashlib.sha256(payload.username.encode("utf-8")).hexdigest()[:12],
        user_id=user.id,
    )
    return AuthSessionResponse(
        user=auth_user_response(user),
        expires_at=auth_session.expires_at,
        session_expires_in_seconds=settings.session_ttl_hours * 3600,
    )


@app.post("/api/signup", response_model=AuthSessionResponse)
async def signup(
    payload: ShopSignupRequest,
    request: Request,
    response: Response,
    db: DbSessionDep,
    settings: SettingsDep,
) -> AuthSessionResponse:
    """Self-service shop signup (/goal Phase 4): creates a brand-new shop
    and its owner account, then logs the new owner in immediately (same
    session/cookie flow as `/api/auth/login`). Also kicks off email
    verification (/goal Phase 5) via the non-sending local/test adapter.
    The session can access `/api/auth/me`, logout, and resend while pending;
    protected business workflows require verification."""
    await enforce_signup_rate_limit(request, settings)
    try:
        owner = await asyncio.to_thread(signup_shop_owner, db, settings, payload)
    except ShopSignupConflictError as exc:
        # exc.reason (e.g. "username_taken" vs. "email_taken") is logged
        # for operators only -- str(exc) (the HTTP response body) is always
        # the same generic message, so an unauthenticated caller can't use
        # this endpoint to enumerate which field of a guess already exists.
        log_security_event(
            logger,
            SecurityEventType.SIGNUP_FAILED,
            request=request,
            reason=exc.reason,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ShopSignupError as exc:
        log_security_event(
            logger,
            SecurityEventType.SIGNUP_FAILED,
            request=request,
            reason="invalid",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    session_token, auth_session = create_auth_session(
        db=db, settings=settings, user=owner, request=request
    )
    set_session_cookie(response, settings, session_token, auth_session.expires_at)
    log_security_event(
        logger,
        SecurityEventType.SIGNUP_SUCCEEDED,
        request=request,
        level=logging.INFO,
        user_id=owner.id,
    )
    try:
        await asyncio.to_thread(request_email_verification, db, settings, owner, email_adapter())
        log_security_event(
            logger,
            SecurityEventType.EMAIL_VERIFICATION_REQUESTED,
            request=request,
            level=logging.INFO,
            user_id=owner.id,
        )
    except EmailVerificationError:
        # Not fatal to account creation. The pending session remains limited
        # to verification/session-recovery routes and can request a new token.
        pass
    return AuthSessionResponse(
        user=auth_user_response(owner),
        expires_at=auth_session.expires_at,
        session_expires_in_seconds=settings.session_ttl_hours * 3600,
    )


@app.post("/api/auth/verify-email/resend")
async def resend_email_verification(
    request: Request,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
) -> dict[str, bool]:
    """Authenticated resend of the /goal Phase 5 email-verification
    message -- open to both roles (a technician account has no email
    today, so this just 422s for one, but there's no reason to bar the
    route itself once one does). Rate-limited per-user (not per-IP,
    since this always requires an existing session -- see
    `enforce_email_verification_resend_rate_limit`)."""
    await enforce_email_verification_resend_rate_limit(request, settings, auth.user.id)
    try:
        await asyncio.to_thread(
            request_email_verification, db, settings, auth.user, email_adapter()
        )
    except EmailVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    log_security_event(
        logger,
        SecurityEventType.EMAIL_VERIFICATION_REQUESTED,
        request=request,
        level=logging.INFO,
        user_id=auth.user.id,
    )
    return {"sent": True}


@app.post("/api/auth/verify-email")
async def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    db: DbSessionDep,
    settings: SettingsDep,
) -> dict[str, bool]:
    """Public (no session required -- the token itself is the credential,
    matching the existing estimate-approval-token pattern) confirmation
    of a /goal Phase 5 email-verification code."""
    await enforce_email_verification_rate_limit(request, settings)
    try:
        user = await asyncio.to_thread(confirm_email_verification, db, payload.token)
    except EmailVerificationTokenError as exc:
        log_security_event(logger, SecurityEventType.EMAIL_VERIFICATION_FAILED, request=request)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    log_security_event(
        logger,
        SecurityEventType.EMAIL_VERIFIED,
        request=request,
        level=logging.INFO,
        user_id=user.id,
    )
    return {"verified": True}


@app.post("/api/auth/password/reset-request")
async def password_reset_request(
    payload: PasswordResetRequest,
    request: Request,
    db: DbSessionDep,
    settings: SettingsDep,
) -> dict[str, bool]:
    """Prepare a reset message without revealing whether the email exists."""
    await enforce_password_reset_rate_limit(request, settings, action="request")
    await asyncio.to_thread(request_password_reset, db, settings, payload.email, email_adapter())
    log_security_event(
        logger,
        SecurityEventType.PASSWORD_RESET_REQUESTED,
        request=request,
        level=logging.INFO,
    )
    return {"accepted": True}


@app.post("/api/auth/password/reset-confirm")
async def password_reset_confirm(
    payload: PasswordResetConfirmRequest,
    request: Request,
    db: DbSessionDep,
    settings: SettingsDep,
) -> dict[str, bool]:
    await enforce_password_reset_rate_limit(request, settings, action="confirm")
    try:
        await asyncio.to_thread(confirm_password_reset, db, payload.token, payload.new_password)
    except PasswordResetTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    log_security_event(
        logger,
        SecurityEventType.PASSWORD_RESET_COMPLETED,
        request=request,
        level=logging.INFO,
    )
    return {"reset": True}


@app.post("/api/invitations/accept", response_model=ShopInvitationAcceptResponse)
async def accept_shop_invitation(
    payload: ShopInvitationAccept,
    request: Request,
    db: DbSessionDep,
    settings: SettingsDep,
) -> ShopInvitationAcceptResponse:
    await enforce_invitation_acceptance_rate_limit(request, settings)
    try:
        user = await asyncio.to_thread(accept_invitation, db, payload)
    except (InvitationError, InvitationConflictError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    log_security_event(
        logger,
        SecurityEventType.INVITATION_ACCEPTED,
        request=request,
        level=logging.INFO,
        user_id=user.id,
    )
    return ShopInvitationAcceptResponse(user=auth_user_response(user))


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
async def auth_me(db: DbSessionDep, auth: AuthContextDep) -> AuthMeResponse:
    return AuthMeResponse(
        user=auth_user_response(auth.user, db=db, session=auth.session),
        expires_at=auth.session.expires_at,
    )


@app.post("/api/auth/password/change")
async def password_change(
    payload: PasswordChangeRequest,
    request: Request,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> dict[str, bool]:
    try:
        await asyncio.to_thread(change_password, db, auth, payload)
    except PasswordChangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    log_security_event(
        logger,
        SecurityEventType.PASSWORD_CHANGED,
        request=request,
        level=logging.INFO,
        user_id=auth.user.id,
    )
    return {"changed": True, "other_sessions_revoked": True}


@app.get("/api/auth/sessions", response_model=AuthSessionListResponse)
async def get_auth_sessions(db: DbSessionDep, auth: AuthContextDep) -> AuthSessionListResponse:
    return await asyncio.to_thread(list_sessions, db, auth)


@app.post("/api/auth/sessions/revoke-others")
async def revoke_other_auth_sessions(
    request: Request,
    db: DbSessionDep,
    auth: AuthContextDep,
) -> dict[str, int]:
    revoked = await asyncio.to_thread(revoke_other_sessions, db, auth)
    log_security_event(
        logger,
        SecurityEventType.SESSION_REVOKED,
        request=request,
        level=logging.INFO,
        user_id=auth.user.id,
        revoked_count=revoked,
    )
    return {"revoked": revoked}


@app.post("/api/auth/sessions/{session_id}/revoke")
async def revoke_auth_session(
    session_id: int,
    request: Request,
    response: Response,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
) -> dict[str, bool]:
    try:
        current = await asyncio.to_thread(revoke_session, db, auth, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if current:
        clear_session_cookie(response, settings)
    log_security_event(
        logger,
        SecurityEventType.SESSION_REVOKED,
        request=request,
        level=logging.INFO,
        user_id=auth.user.id,
        current_session=current,
    )
    return {"revoked": True, "current_session": current}


@app.get("/api/auth/login-history", response_model=AuthLoginHistoryResponse)
async def get_login_history(db: DbSessionDep, auth: AuthContextDep) -> AuthLoginHistoryResponse:
    return await asyncio.to_thread(login_history, db, auth)


@app.get("/api/auth/security", response_model=AccountSecurityRead)
async def get_account_security(db: DbSessionDep, auth: AuthContextDep) -> AccountSecurityRead:
    return await asyncio.to_thread(security_summary, db, auth)


@app.post("/api/shop/invitations", response_model=ShopInvitationRead)
async def prepare_shop_invitation(
    payload: ShopInvitationCreate,
    request: Request,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
) -> ShopInvitationRead:
    try:
        invitation = await asyncio.to_thread(
            create_invitation, db, settings, auth, payload, email_adapter()
        )
    except InvitationConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvitationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    log_security_event(
        logger,
        SecurityEventType.INVITATION_CREATED,
        request=request,
        level=logging.INFO,
        user_id=auth.user.id,
        invitation_id=invitation.id,
    )
    return invitation


@app.get("/api/shop/invitations", response_model=list[ShopInvitationRead])
async def get_shop_invitations(
    db: DbSessionDep, auth: OwnerAuthContextDep
) -> list[ShopInvitationRead]:
    return await asyncio.to_thread(list_invitations, db, auth)


@app.post("/api/shop/invitations/{invitation_id}/revoke")
async def revoke_shop_invitation(
    invitation_id: int,
    request: Request,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> dict[str, bool]:
    try:
        await asyncio.to_thread(revoke_invitation, db, auth, invitation_id)
    except InvitationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    log_security_event(
        logger,
        SecurityEventType.INVITATION_REVOKED,
        request=request,
        level=logging.INFO,
        user_id=auth.user.id,
        invitation_id=invitation_id,
    )
    return {"revoked": True}


@app.get("/api/shop/members", response_model=list[ShopMemberRead])
async def get_shop_members(db: DbSessionDep, auth: OwnerAuthContextDep) -> list[ShopMemberRead]:
    return await asyncio.to_thread(list_members, db, auth)


@app.patch("/api/shop/members/{user_account_id}/status", response_model=ShopMemberRead)
async def change_shop_member_status(
    user_account_id: int,
    payload: AccountStatusUpdate,
    request: Request,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> ShopMemberRead:
    try:
        member = await asyncio.to_thread(update_member_status, db, auth, user_account_id, payload)
    except MemberManagementError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    log_security_event(
        logger,
        SecurityEventType.ACCOUNT_STATUS_CHANGED,
        request=request,
        level=logging.INFO,
        user_id=auth.user.id,
        target_user_id=user_account_id,
        account_status=payload.status,
    )
    return member


def _require_square_configured(settings: Settings) -> None:
    if not settings.square_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Square is not configured (sandbox only in this phase).",
        )


@app.get("/api/billing/subscription", response_model=SubscriptionRead)
async def get_billing_subscription(
    db: DbSessionDep, auth: BillingAuthContextDep
) -> SubscriptionRead:
    try:
        return await asyncio.to_thread(get_subscription, db, auth)
    except SubscriptionStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Subscription lookup failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription storage is unavailable.",
        ) from exc


@app.get("/api/billing/events", response_model=SubscriptionEventsResponse)
async def list_billing_events(
    db: DbSessionDep, auth: BillingAuthContextDep
) -> SubscriptionEventsResponse:
    return await asyncio.to_thread(list_subscription_events, db, auth)


@app.post("/api/billing/payment-method", response_model=SubscriptionRead)
async def add_billing_payment_method(
    payload: AddPaymentMethodRequest,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: BillingAuthContextDep,
) -> SubscriptionRead:
    _require_square_configured(settings)
    client = SquareSubscriptionClient(settings)
    try:
        return await asyncio.to_thread(
            lambda: add_payment_method(db, auth, client=client, source_id=payload.source_id)
        )
    except SubscriptionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SubscriptionStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SquareApiError as exc:
        log_security_event(
            logger,
            SecurityEventType.SQUARE_API_FAILED,
            actor_type=ActorType.USER,
            actor_id=auth.user.id,
            actor_label=auth.user.username,
            operation="add_payment_method",
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Payment method update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription storage is unavailable.",
        ) from exc
    finally:
        client.close()


@app.post("/api/billing/subscribe", response_model=SubscriptionRead)
async def subscribe_billing(
    payload: SubscribeRequest,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: BillingAuthContextDep,
) -> SubscriptionRead:
    _require_square_configured(settings)
    client = SquareSubscriptionClient(settings)
    try:
        return await asyncio.to_thread(
            lambda: subscribe_shop(db, auth, settings=settings, client=client, tier=payload.tier)
        )
    except SubscriptionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SubscriptionStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SquareApiError as exc:
        log_security_event(
            logger,
            SecurityEventType.SQUARE_API_FAILED,
            actor_type=ActorType.USER,
            actor_id=auth.user.id,
            actor_label=auth.user.username,
            operation="subscribe",
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Subscribe failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription storage is unavailable.",
        ) from exc
    finally:
        client.close()


@app.post("/api/billing/tier", response_model=SubscriptionRead)
async def change_billing_tier(
    payload: SubscribeRequest,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: BillingAuthContextDep,
) -> SubscriptionRead:
    client = SquareSubscriptionClient(settings) if settings.square_configured else None
    try:
        return await asyncio.to_thread(
            lambda: change_tier(db, auth, settings=settings, client=client, tier=payload.tier)
        )
    except SubscriptionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SubscriptionStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SquareApiError as exc:
        log_security_event(
            logger,
            SecurityEventType.SQUARE_API_FAILED,
            actor_type=ActorType.USER,
            actor_id=auth.user.id,
            actor_label=auth.user.username,
            operation="change_tier",
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Tier change failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription storage is unavailable.",
        ) from exc
    finally:
        if client is not None:
            client.close()


@app.post("/api/billing/cancel", response_model=SubscriptionRead)
async def cancel_billing_subscription(
    db: DbSessionDep, settings: SettingsDep, auth: BillingAuthContextDep
) -> SubscriptionRead:
    client = SquareSubscriptionClient(settings) if settings.square_configured else None
    try:
        return await asyncio.to_thread(lambda: cancel_subscription(db, auth, client=client))
    except SubscriptionStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SquareApiError as exc:
        log_security_event(
            logger,
            SecurityEventType.SQUARE_API_FAILED,
            actor_type=ActorType.USER,
            actor_id=auth.user.id,
            actor_label=auth.user.username,
            operation="cancel",
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Subscription cancel failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription storage is unavailable.",
        ) from exc
    finally:
        if client is not None:
            client.close()


@app.post("/api/billing/refresh", response_model=SubscriptionRead)
async def refresh_billing_subscription(
    db: DbSessionDep, settings: SettingsDep, auth: BillingAuthContextDep
) -> SubscriptionRead:
    _require_square_configured(settings)
    client = SquareSubscriptionClient(settings)
    try:
        return await asyncio.to_thread(
            lambda: refresh_subscription_from_square(db, auth, client=client)
        )
    except SubscriptionStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SquareApiError as exc:
        log_security_event(
            logger,
            SecurityEventType.SQUARE_API_FAILED,
            actor_type=ActorType.USER,
            actor_id=auth.user.id,
            actor_label=auth.user.username,
            operation="refresh",
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Subscription refresh failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription storage is unavailable.",
        ) from exc
    finally:
        client.close()


@app.get("/api/support/shops", response_model=SupportShopListResponse)
async def list_support_shops(
    request: Request, db: DbSessionDep, auth: SupportAuthContextDep
) -> SupportShopListResponse:
    result = await asyncio.to_thread(list_shops_for_support, db)
    log_security_event(
        logger,
        SecurityEventType.SUPPORT_DIRECTORY_VIEWED,
        request=request,
        level=logging.INFO,
        user_id=auth.user.id,
        shop_count=len(result.items),
    )
    return result


@app.post("/api/support/shops/{shop_id}/impersonate", response_model=AuthSessionResponse)
async def start_shop_impersonation(
    shop_id: int,
    request: Request,
    response: Response,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: SupportAuthContextDep,
) -> AuthSessionResponse:
    try:
        token, auth_session, owner = await asyncio.to_thread(
            impersonate_shop_owner,
            db,
            auth,
            settings=settings,
            shop_id=shop_id,
            request=request,
        )
    except SupportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    set_session_cookie(response, settings, token, auth_session.expires_at)
    log_security_event(
        logger,
        SecurityEventType.SUPPORT_IMPERSONATION_STARTED,
        request=request,
        level=logging.INFO,
        support_user_id=auth.user.id,
        shop_id=shop_id,
        target_owner_id=owner.id,
    )
    return AuthSessionResponse(
        user=auth_user_response(owner, db=db, session=auth_session),
        expires_at=auth_session.expires_at,
        session_expires_in_seconds=int(
            (auth_session.expires_at - datetime.now(UTC)).total_seconds()
        ),
    )


@app.post("/api/support/end-impersonation", response_model=AuthSessionResponse)
async def end_shop_impersonation_route(
    request: Request,
    response: Response,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: AuthContextDep,
) -> AuthSessionResponse:
    token, auth_session, support_user = await asyncio.to_thread(
        end_shop_impersonation, db, auth, settings=settings, request=request
    )
    set_session_cookie(response, settings, token, auth_session.expires_at)
    log_security_event(
        logger,
        SecurityEventType.SUPPORT_IMPERSONATION_ENDED,
        request=request,
        level=logging.INFO,
        support_user_id=support_user.id,
    )
    return AuthSessionResponse(
        user=auth_user_response(support_user),
        expires_at=auth_session.expires_at,
        session_expires_in_seconds=int(
            (auth_session.expires_at - datetime.now(UTC)).total_seconds()
        ),
    )


def _require_test_support_enabled(settings: Settings) -> None:
    # Returns 404, not 403 -- when disabled (the default in every real
    # deployment), these routes should not even reveal they exist.
    if not provisioning_enabled(settings):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@app.post("/api/test-support/synthetic-owner", response_model=SyntheticAccountResponse)
async def create_synthetic_owner(
    db: DbSessionDep,
    settings: SettingsDep,
) -> SyntheticAccountResponse:
    """Provision a synthetic owner account for automated/CI end-to-end tests.

    Disabled unless OPTIMUS_TEST_ACCOUNT_PROVISIONING is true and APP_ENV is
    not "production" -- see app/test_support_store.py.
    """
    _require_test_support_enabled(settings)
    try:
        account = await asyncio.to_thread(provision_synthetic_owner, db=db, settings=settings)
    except TestSupportDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except SQLAlchemyError as exc:
        logger.warning("Synthetic owner provisioning failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Synthetic account storage is unavailable.",
        ) from exc
    return SyntheticAccountResponse(
        user_id=account.user_id,
        username=account.username,
        password=account.password,
        role=account.role,
        technician_id=account.technician_id,
    )


@app.post("/api/test-support/synthetic-technician", response_model=SyntheticAccountResponse)
async def create_synthetic_technician(
    payload: SyntheticTechnicianRequest,
    db: DbSessionDep,
    settings: SettingsDep,
) -> SyntheticAccountResponse:
    """Provision a synthetic technician under an existing synthetic owner."""
    _require_test_support_enabled(settings)
    try:
        account = await asyncio.to_thread(
            provision_synthetic_technician,
            db=db,
            settings=settings,
            owner_username=payload.owner_username,
        )
    except TestSupportDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except SyntheticOwnerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except TestSupportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except SQLAlchemyError as exc:
        logger.warning("Synthetic technician provisioning failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Synthetic account storage is unavailable.",
        ) from exc
    return SyntheticAccountResponse(
        user_id=account.user_id,
        username=account.username,
        password=account.password,
        role=account.role,
        technician_id=account.technician_id,
    )


@app.delete(
    "/api/test-support/synthetic-accounts/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_synthetic_account(
    user_id: int,
    db: DbSessionDep,
    settings: SettingsDep,
) -> Response:
    """Delete one synthetic account (and everything it owns, via cascade).

    Refuses to delete anything that isn't flagged as a synthetic test
    account, even if the id belongs to a real user -- this can never be used
    to delete a real owner or technician account.
    """
    _require_test_support_enabled(settings)
    try:
        deleted = await asyncio.to_thread(
            cleanup_synthetic_account, db=db, settings=settings, user_id=user_id
        )
    except TestSupportDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except SQLAlchemyError as exc:
        logger.warning("Synthetic account cleanup failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Synthetic account storage is unavailable.",
        ) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.delete("/api/test-support/synthetic-accounts", response_model=SyntheticCleanupResponse)
async def delete_all_synthetic_accounts(
    db: DbSessionDep,
    settings: SettingsDep,
) -> SyntheticCleanupResponse:
    """Sweep-cleanup every synthetic owner account (and everything cascaded from it).

    Intended for CI teardown so a failed test run can't leave synthetic data
    behind even if individual per-account cleanup was skipped.
    """
    _require_test_support_enabled(settings)
    try:
        count = await asyncio.to_thread(cleanup_all_synthetic_accounts, db=db, settings=settings)
    except TestSupportDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except SQLAlchemyError as exc:
        logger.warning("Synthetic account sweep-cleanup failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Synthetic account storage is unavailable.",
        ) from exc
    return SyntheticCleanupResponse(deleted_count=count)


@app.post("/api/test-support/concurrency-probe/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_concurrency_probe_record(settings: SettingsDep) -> None:
    """Resets the concurrency probe's shared in-flight/max-observed
    counters. Call before a batch of concurrent probe requests so a
    previous test's leftover state can't inflate this one's result."""
    _require_test_support_enabled(settings)
    reset_concurrency_probe()


@app.get("/api/test-support/concurrency-probe", response_model=ConcurrencyProbeResponse)
async def get_concurrency_probe_record(
    settings: SettingsDep, delay_ms: int = Query(default=200, ge=1, le=5000)
) -> ConcurrencyProbeResponse:
    """Sleeps for `delay_ms` while tracking how many concurrent calls to
    this route were in flight at once, process-wide -- proof that request
    handling is no longer serialized (Phase 1 of the /goal roadmap: this
    route's blocking work is offloaded via `asyncio.to_thread`, same as
    every other route in this app). See
    `tests/e2e/test_request_concurrency.py`. Gated the same way as every
    other `/api/test-support/*` route -- off by default, off in production.
    """
    _require_test_support_enabled(settings)
    max_observed = await asyncio.to_thread(concurrency_probe, delay_ms)
    return ConcurrencyProbeResponse(max_observed_in_flight=max_observed)


@app.post("/api/customers", response_model=CustomerRead)
async def create_customer_record(
    payload: CustomerCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> CustomerRead:
    try:
        return await asyncio.to_thread(create_customer, db=db, auth=auth, payload=payload)
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
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    search: str | None = Query(default=None, max_length=120),
    archived: bool = False,
) -> CustomerListResponse:
    try:
        return await asyncio.to_thread(
            list_customers,
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
    auth: OwnerAuthContextDep,
) -> CustomerRead:
    try:
        return await asyncio.to_thread(get_customer, db=db, auth=auth, customer_id=customer_id)
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
    auth: OwnerAuthContextDep,
) -> CustomerRead:
    try:
        return await asyncio.to_thread(
            update_customer, db=db, auth=auth, customer_id=customer_id, payload=payload
        )
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
    auth: OwnerAuthContextDep,
) -> CustomerArchiveResponse:
    try:
        return await asyncio.to_thread(archive_customer, db=db, auth=auth, customer_id=customer_id)
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
    auth: OwnerAuthContextDep,
) -> VehicleRead:
    try:
        return await asyncio.to_thread(
            create_vehicle, db=db, auth=auth, customer_id=customer_id, payload=payload
        )
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
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    search: str | None = Query(default=None, max_length=120),
    archived: bool = False,
) -> VehicleListResponse:
    try:
        return await asyncio.to_thread(
            list_vehicles,
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


@app.get("/api/customers/{customer_id}/history", response_model=CustomerHistoryResponse)
async def get_customer_history_record(
    customer_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
    limit: int = Query(default=20, ge=1, le=50),
) -> CustomerHistoryResponse:
    try:
        return await asyncio.to_thread(
            get_customer_history, db=db, auth=auth, customer_id=customer_id, limit=limit
        )
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Customer history lookup failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Customer history storage is unavailable.",
        ) from exc


@app.get("/api/vehicles", response_model=VehicleListResponse)
async def list_vehicle_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    search: str | None = Query(default=None, max_length=120),
    customer_id: int | None = Query(default=None, ge=1),
    archived: bool = False,
) -> VehicleListResponse:
    try:
        return await asyncio.to_thread(
            list_vehicles,
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
    auth: OwnerAuthContextDep,
) -> VehicleRead:
    try:
        return await asyncio.to_thread(get_vehicle, db=db, auth=auth, vehicle_id=vehicle_id)
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
    auth: OwnerAuthContextDep,
) -> VehicleRead:
    try:
        return await asyncio.to_thread(
            update_vehicle, db=db, auth=auth, vehicle_id=vehicle_id, payload=payload
        )
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
    auth: OwnerAuthContextDep,
) -> VehicleArchiveResponse:
    try:
        return await asyncio.to_thread(archive_vehicle, db=db, auth=auth, vehicle_id=vehicle_id)
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


@app.post("/api/technicians", response_model=TechnicianRead)
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


@app.get("/api/technicians", response_model=TechnicianListResponse)
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


@app.get("/api/technicians/me", response_model=TechnicianMeResponse)
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


@app.post("/api/technicians/me/clock-in", response_model=TechnicianClockResponse)
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


@app.post("/api/technicians/me/clock-out", response_model=TechnicianClockResponse)
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


@app.get("/api/technicians/{technician_id}", response_model=TechnicianRead)
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


@app.patch("/api/technicians/{technician_id}", response_model=TechnicianRead)
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


@app.delete("/api/technicians/{technician_id}", response_model=TechnicianArchiveResponse)
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


@app.post(
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


@app.post("/api/vendors", response_model=VendorRead)
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


@app.get("/api/vendors", response_model=VendorListResponse)
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


@app.get("/api/vendors/{vendor_id}", response_model=VendorRead)
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


@app.patch("/api/vendors/{vendor_id}", response_model=VendorRead)
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


@app.delete("/api/vendors/{vendor_id}", response_model=VendorArchiveResponse)
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


@app.post("/api/parts", response_model=PartRead)
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


@app.get("/api/parts", response_model=PartListResponse)
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


@app.get("/api/parts/{part_id}", response_model=PartRead)
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


@app.patch("/api/parts/{part_id}", response_model=PartRead)
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


@app.delete("/api/parts/{part_id}", response_model=PartArchiveResponse)
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


@app.post("/api/purchase-orders", response_model=PurchaseOrderRead)
async def create_purchase_order_record(
    payload: PurchaseOrderCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PurchaseOrderRead:
    try:
        return await asyncio.to_thread(create_purchase_order, db=db, auth=auth, payload=payload)
    except PurchaseOrderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Purchase order creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Purchase order storage is unavailable.",
        ) from exc


@app.get("/api/purchase-orders", response_model=PurchaseOrderListResponse)
async def list_purchase_order_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    status_filter: PurchaseOrderStatus | None = None,
    vendor_id: int | None = Query(default=None, ge=1),
) -> PurchaseOrderListResponse:
    try:
        return await asyncio.to_thread(
            list_purchase_orders,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            status=status_filter,
            vendor_id=vendor_id,
        )
    except PurchaseOrderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Purchase order listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Purchase order storage is unavailable.",
        ) from exc


@app.get("/api/purchase-orders/{purchase_order_id}", response_model=PurchaseOrderRead)
async def get_purchase_order_record(
    purchase_order_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PurchaseOrderRead:
    try:
        return await asyncio.to_thread(
            get_purchase_order, db=db, auth=auth, purchase_order_id=purchase_order_id
        )
    except PurchaseOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Purchase order retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Purchase order storage is unavailable.",
        ) from exc


@app.post("/api/purchase-orders/{purchase_order_id}/submit", response_model=PurchaseOrderRead)
async def submit_purchase_order_record(
    purchase_order_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PurchaseOrderRead:
    try:
        return await asyncio.to_thread(
            submit_purchase_order, db=db, auth=auth, purchase_order_id=purchase_order_id
        )
    except PurchaseOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PurchaseOrderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Purchase order submission failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Purchase order storage is unavailable.",
        ) from exc


@app.post("/api/purchase-orders/{purchase_order_id}/cancel", response_model=PurchaseOrderRead)
async def cancel_purchase_order_record(
    purchase_order_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PurchaseOrderRead:
    try:
        return await asyncio.to_thread(
            cancel_purchase_order, db=db, auth=auth, purchase_order_id=purchase_order_id
        )
    except PurchaseOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PurchaseOrderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Purchase order cancellation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Purchase order storage is unavailable.",
        ) from exc


@app.post("/api/purchase-orders/{purchase_order_id}/receive", response_model=PurchaseOrderRead)
async def receive_purchase_order_record(
    purchase_order_id: int,
    payload: PurchaseOrderReceiveRequest,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PurchaseOrderRead:
    try:
        return await asyncio.to_thread(
            receive_purchase_order_line_item,
            db=db,
            auth=auth,
            purchase_order_id=purchase_order_id,
            payload=payload,
        )
    except PurchaseOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PurchaseOrderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Purchase order receiving failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Purchase order storage is unavailable.",
        ) from exc


@app.get(
    "/api/purchase-orders/{purchase_order_id}/receipts",
    response_model=PurchaseOrderReceiptsResponse,
)
async def list_purchase_order_receipt_records(
    purchase_order_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PurchaseOrderReceiptsResponse:
    try:
        return await asyncio.to_thread(
            list_purchase_order_receipts, db=db, auth=auth, purchase_order_id=purchase_order_id
        )
    except PurchaseOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Purchase order receipt listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Purchase order storage is unavailable.",
        ) from exc


@app.post(
    "/api/work-orders/{work_order_id}/part-allocations",
    response_model=PartAllocationRead | PartAllocationTechnicianRead,
)
async def create_part_allocation_record(
    work_order_id: int,
    payload: PartAllocationCreate,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> PartAllocationRead | PartAllocationTechnicianRead:
    try:
        return await asyncio.to_thread(
            create_part_allocation, db=db, auth=auth, work_order_id=work_order_id, payload=payload
        )
    except PartAllocationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part allocation creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part allocation storage is unavailable.",
        ) from exc


@app.get(
    "/api/work-orders/{work_order_id}/part-allocations", response_model=PartAllocationListResponse
)
async def list_part_allocation_records(
    work_order_id: int,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> PartAllocationListResponse:
    try:
        return await asyncio.to_thread(
            list_part_allocations, db=db, auth=auth, work_order_id=work_order_id
        )
    except PartAllocationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part allocation listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part allocation storage is unavailable.",
        ) from exc


@app.get(
    "/api/part-allocations/{allocation_id}",
    response_model=PartAllocationRead | PartAllocationTechnicianRead,
)
async def get_part_allocation_record(
    allocation_id: int,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> PartAllocationRead | PartAllocationTechnicianRead:
    try:
        return await asyncio.to_thread(
            get_part_allocation, db=db, auth=auth, allocation_id=allocation_id
        )
    except PartAllocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part allocation retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part allocation storage is unavailable.",
        ) from exc


@app.post(
    "/api/part-allocations/{allocation_id}/allocate",
    response_model=PartAllocationRead | PartAllocationTechnicianRead,
)
async def allocate_part_record(
    allocation_id: int,
    payload: PartAllocationAllocateRequest,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> PartAllocationRead | PartAllocationTechnicianRead:
    try:
        return await asyncio.to_thread(
            allocate_part, db=db, auth=auth, allocation_id=allocation_id, payload=payload
        )
    except PartAllocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PartAllocationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part allocation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part allocation storage is unavailable.",
        ) from exc


@app.post(
    "/api/part-allocations/{allocation_id}/use",
    response_model=PartAllocationRead | PartAllocationTechnicianRead,
)
async def use_part_allocation_record(
    allocation_id: int,
    payload: PartAllocationUseRequest,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> PartAllocationRead | PartAllocationTechnicianRead:
    try:
        return await asyncio.to_thread(
            use_part_allocation, db=db, auth=auth, allocation_id=allocation_id, payload=payload
        )
    except PartAllocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PartAllocationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Marking a part allocation used failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part allocation storage is unavailable.",
        ) from exc


@app.post(
    "/api/part-allocations/{allocation_id}/return",
    response_model=PartAllocationRead | PartAllocationTechnicianRead,
)
async def return_part_allocation_record(
    allocation_id: int,
    payload: PartAllocationReturnRequest,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> PartAllocationRead | PartAllocationTechnicianRead:
    try:
        return await asyncio.to_thread(
            return_part_allocation, db=db, auth=auth, allocation_id=allocation_id, payload=payload
        )
    except PartAllocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PartAllocationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part allocation return failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part allocation storage is unavailable.",
        ) from exc


@app.get(
    "/api/part-allocations/{allocation_id}/events", response_model=PartAllocationEventsResponse
)
async def list_part_allocation_event_records(
    allocation_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> PartAllocationEventsResponse:
    try:
        return await asyncio.to_thread(
            list_part_allocation_events, db=db, auth=auth, allocation_id=allocation_id
        )
    except PartAllocationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Part allocation event listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Part allocation storage is unavailable.",
        ) from exc


@app.post("/api/workflow-gaps", response_model=WorkflowGapRead)
async def create_workflow_gap_record(
    payload: WorkflowGapCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> WorkflowGapRead:
    try:
        return await asyncio.to_thread(create_workflow_gap, db, auth, payload)
    except WorkflowGapStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Workflow gap creation failed due to storage error.")
        raise HTTPException(status_code=503, detail="Workflow-gap storage is unavailable.") from exc


@app.get("/api/workflow-gaps", response_model=WorkflowGapListResponse)
async def list_workflow_gap_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
    search: str | None = Query(default=None, max_length=120),
    status_filter: Annotated[WorkflowGapStatus | None, Query(alias="status")] = None,
    severity_filter: Annotated[WorkflowGapSeverity | None, Query(alias="severity")] = None,
) -> WorkflowGapListResponse:
    try:
        return await asyncio.to_thread(
            list_workflow_gaps,
            db,
            auth,
            settings,
            page=page,
            page_size=page_size,
            status_filter=status_filter,
            severity_filter=severity_filter,
            search=search,
        )
    except WorkflowGapStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Workflow gap listing failed due to storage error.")
        raise HTTPException(status_code=503, detail="Workflow-gap storage is unavailable.") from exc


@app.get("/api/workflow-gaps/{workflow_gap_id}", response_model=WorkflowGapRead)
async def get_workflow_gap_record(
    workflow_gap_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> WorkflowGapRead:
    try:
        return await asyncio.to_thread(get_workflow_gap, db, auth, workflow_gap_id)
    except WorkflowGapNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Workflow gap retrieval failed due to storage error.")
        raise HTTPException(status_code=503, detail="Workflow-gap storage is unavailable.") from exc


@app.patch("/api/workflow-gaps/{workflow_gap_id}", response_model=WorkflowGapRead)
async def update_workflow_gap_record(
    workflow_gap_id: int,
    payload: WorkflowGapUpdate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> WorkflowGapRead:
    try:
        return await asyncio.to_thread(update_workflow_gap, db, auth, workflow_gap_id, payload)
    except WorkflowGapNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowGapConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowGapStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Workflow gap update failed due to storage error.")
        raise HTTPException(status_code=503, detail="Workflow-gap storage is unavailable.") from exc


@app.post("/api/workflow-gaps/{workflow_gap_id}/occurrences", response_model=WorkflowGapRead)
async def record_workflow_gap_occurrence_record(
    workflow_gap_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> WorkflowGapRead:
    try:
        return await asyncio.to_thread(record_workflow_gap_occurrence, db, auth, workflow_gap_id)
    except WorkflowGapNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowGapConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Workflow gap occurrence failed due to storage error.")
        raise HTTPException(status_code=503, detail="Workflow-gap storage is unavailable.") from exc


@app.get(
    "/api/workflow-gaps/{workflow_gap_id}/events",
    response_model=WorkflowGapEventsResponse,
)
async def list_workflow_gap_event_records(
    workflow_gap_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> WorkflowGapEventsResponse:
    try:
        return await asyncio.to_thread(list_workflow_gap_events, db, auth, workflow_gap_id)
    except WorkflowGapNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Workflow gap event listing failed due to storage error.")
        raise HTTPException(status_code=503, detail="Workflow-gap storage is unavailable.") from exc


@app.post("/api/intake-requests", response_model=IntakeRequestRead)
async def create_intake_request_record(
    payload: IntakeRequestCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> IntakeRequestRead:
    try:
        return await asyncio.to_thread(create_intake_request, db=db, auth=auth, payload=payload)
    except IntakeStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Intake request creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Intake request storage is unavailable.",
        ) from exc


@app.get("/api/intake-requests", response_model=IntakeRequestListResponse)
async def list_intake_request_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    search: str | None = Query(default=None, max_length=120),
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> IntakeRequestListResponse:
    try:
        return await asyncio.to_thread(
            list_intake_requests,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            status_filter=status_filter,
            search=search,
        )
    except IntakeStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Intake request listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Intake request storage is unavailable.",
        ) from exc


@app.get("/api/intake-requests/{intake_request_id}", response_model=IntakeRequestRead)
async def get_intake_request_record(
    intake_request_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> IntakeRequestRead:
    try:
        return await asyncio.to_thread(
            get_intake_request, db=db, auth=auth, intake_request_id=intake_request_id
        )
    except IntakeRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntakeStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Intake request retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Intake request storage is unavailable.",
        ) from exc


@app.patch("/api/intake-requests/{intake_request_id}", response_model=IntakeRequestRead)
async def update_intake_request_record(
    intake_request_id: int,
    payload: IntakeRequestUpdate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> IntakeRequestRead:
    try:
        return await asyncio.to_thread(
            update_intake_request,
            db=db,
            auth=auth,
            intake_request_id=intake_request_id,
            payload=payload,
        )
    except IntakeRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntakeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntakeStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Intake request update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Intake request storage is unavailable.",
        ) from exc


@app.post(
    "/api/intake-requests/{intake_request_id}/convert",
    response_model=IntakeRequestConvertResponse,
)
async def convert_intake_request_record(
    intake_request_id: int,
    payload: IntakeRequestConvertRequest,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> IntakeRequestConvertResponse:
    try:
        return await asyncio.to_thread(
            convert_intake_request,
            db=db,
            auth=auth,
            intake_request_id=intake_request_id,
            payload=payload,
        )
    except IntakeRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntakeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntakeStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Intake request conversion failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Intake request storage is unavailable.",
        ) from exc


@app.post("/api/diagnostic-findings", response_model=DiagnosticFindingRead)
async def create_diagnostic_finding_record(
    payload: DiagnosticFindingCreate,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> DiagnosticFindingRead:
    try:
        return await asyncio.to_thread(create_diagnostic_finding, db=db, auth=auth, payload=payload)
    except DiagnosticsStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Diagnostic finding creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Diagnostic finding storage is unavailable.",
        ) from exc


@app.get("/api/diagnostic-findings", response_model=DiagnosticFindingListResponse)
async def list_diagnostic_finding_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerOrTechnicianAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    vehicle_id: int | None = Query(default=None, ge=1),
    work_order_id: int | None = Query(default=None, ge=1),
    archived: bool = False,
) -> DiagnosticFindingListResponse:
    try:
        return await asyncio.to_thread(
            list_diagnostic_findings,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            vehicle_id=vehicle_id,
            work_order_id=work_order_id,
            archived=archived,
        )
    except DiagnosticsStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Diagnostic finding listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Diagnostic finding storage is unavailable.",
        ) from exc


@app.get("/api/diagnostic-findings/{finding_id}", response_model=DiagnosticFindingRead)
async def get_diagnostic_finding_record(
    finding_id: int,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> DiagnosticFindingRead:
    try:
        return await asyncio.to_thread(
            get_diagnostic_finding, db=db, auth=auth, finding_id=finding_id
        )
    except DiagnosticFindingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DiagnosticsStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Diagnostic finding retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Diagnostic finding storage is unavailable.",
        ) from exc


@app.patch("/api/diagnostic-findings/{finding_id}", response_model=DiagnosticFindingRead)
async def update_diagnostic_finding_record(
    finding_id: int,
    payload: DiagnosticFindingUpdate,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> DiagnosticFindingRead:
    try:
        return await asyncio.to_thread(
            update_diagnostic_finding, db=db, auth=auth, finding_id=finding_id, payload=payload
        )
    except DiagnosticFindingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DiagnosticsStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Diagnostic finding update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Diagnostic finding storage is unavailable.",
        ) from exc


@app.delete(
    "/api/diagnostic-findings/{finding_id}", response_model=DiagnosticFindingArchiveResponse
)
async def archive_diagnostic_finding_record(
    finding_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> DiagnosticFindingArchiveResponse:
    try:
        return await asyncio.to_thread(
            archive_diagnostic_finding, db=db, auth=auth, finding_id=finding_id
        )
    except DiagnosticFindingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Diagnostic finding archive failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Diagnostic finding storage is unavailable.",
        ) from exc


@app.get(
    "/api/diagnostic-findings/{finding_id}/events", response_model=DiagnosticFindingEventsResponse
)
async def list_diagnostic_finding_event_records(
    finding_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> DiagnosticFindingEventsResponse:
    try:
        return await asyncio.to_thread(
            list_diagnostic_finding_events, db=db, auth=auth, finding_id=finding_id
        )
    except DiagnosticFindingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Diagnostic finding event listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Diagnostic finding storage is unavailable.",
        ) from exc


@app.post("/api/inspections", response_model=InspectionRead)
async def create_inspection_record(
    payload: InspectionCreate,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> InspectionRead:
    try:
        return await asyncio.to_thread(create_inspection, db=db, auth=auth, payload=payload)
    except InspectionStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Inspection creation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inspection storage is unavailable.",
        ) from exc


@app.get("/api/inspections", response_model=InspectionListResponse)
async def list_inspection_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerOrTechnicianAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    vehicle_id: int | None = Query(default=None, ge=1),
    work_order_id: int | None = Query(default=None, ge=1),
    archived: bool = False,
) -> InspectionListResponse:
    try:
        return await asyncio.to_thread(
            list_inspections,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            vehicle_id=vehicle_id,
            work_order_id=work_order_id,
            archived=archived,
        )
    except InspectionStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Inspection listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inspection storage is unavailable.",
        ) from exc


@app.get("/api/inspections/{inspection_id}", response_model=InspectionRead)
async def get_inspection_record(
    inspection_id: int,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> InspectionRead:
    try:
        return await asyncio.to_thread(
            get_inspection, db=db, auth=auth, inspection_id=inspection_id
        )
    except InspectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InspectionStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Inspection retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inspection storage is unavailable.",
        ) from exc


@app.patch("/api/inspections/{inspection_id}", response_model=InspectionRead)
async def update_inspection_record(
    inspection_id: int,
    payload: InspectionUpdate,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> InspectionRead:
    try:
        return await asyncio.to_thread(
            update_inspection, db=db, auth=auth, inspection_id=inspection_id, payload=payload
        )
    except InspectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InspectionStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Inspection update failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inspection storage is unavailable.",
        ) from exc


@app.delete("/api/inspections/{inspection_id}", response_model=InspectionArchiveResponse)
async def archive_inspection_record(
    inspection_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> InspectionArchiveResponse:
    try:
        return await asyncio.to_thread(
            archive_inspection, db=db, auth=auth, inspection_id=inspection_id
        )
    except InspectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Inspection archive failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inspection storage is unavailable.",
        ) from exc


@app.get("/api/inspections/{inspection_id}/events", response_model=InspectionEventsResponse)
async def list_inspection_event_records(
    inspection_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> InspectionEventsResponse:
    try:
        return await asyncio.to_thread(
            list_inspection_events, db=db, auth=auth, inspection_id=inspection_id
        )
    except InspectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Inspection event listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inspection storage is unavailable.",
        ) from exc


@app.get("/api/context/{project_key}", response_model=ContextListResponse)
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


@app.put("/api/context/{project_key}/{context_key}", response_model=ContextEntryRead)
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


@app.delete("/api/context/{project_key}/{context_key}", response_model=ContextDeleteResponse)
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


@app.post("/api/estimates", response_model=EstimateRead)
async def create_estimate_record(
    payload: EstimateCreate,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
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
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    status_filter: Annotated[EstimateStatus | None, Query(alias="status")] = None,
    search: str | None = Query(default=None, max_length=120),
    customer_id: int | None = Query(default=None, ge=1),
    vehicle_id: int | None = Query(default=None, ge=1),
    archived: bool = False,
) -> EstimateListResponse:
    try:
        return await asyncio.to_thread(
            list_estimates,
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
    auth: OwnerAuthContextDep,
) -> EstimateRead:
    try:
        return await asyncio.to_thread(get_estimate, db=db, auth=auth, estimate_id=estimate_id)
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
    auth: OwnerAuthContextDep,
) -> EstimateRead:
    try:
        return await asyncio.to_thread(
            update_estimate, db=db, auth=auth, estimate_id=estimate_id, payload=payload
        )
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
    auth: OwnerAuthContextDep,
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
    auth: OwnerAuthContextDep,
    request_context: Request,
) -> EstimateApprovalSendResponse:
    del request_context
    try:
        return await asyncio.to_thread(
            send_estimate_for_approval,
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


@app.post(
    "/api/estimates/{estimate_id}/approval-requests/{approval_request_id}/revoke",
    response_model=EstimateRead,
)
async def revoke_estimate_approval_request_record(
    estimate_id: int,
    approval_request_id: int,
    payload: EstimateApprovalRevokeRequest,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> EstimateRead:
    try:
        return await asyncio.to_thread(
            revoke_estimate_approval_request,
            db=db,
            auth=auth,
            estimate_id=estimate_id,
            approval_request_id=approval_request_id,
            reason=payload.reason,
        )
    except EstimateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EstimateStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Estimate approval-link revoke failed due to storage error.")
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
        return await asyncio.to_thread(get_approval_view, db=db, payload=payload)
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
        return await asyncio.to_thread(
            approve_estimate,
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
        return await asyncio.to_thread(
            decline_estimate,
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
    auth: OwnerAuthContextDep,
) -> EstimateApprovalAuditResponse:
    try:
        return await asyncio.to_thread(approval_history, db=db, auth=auth, estimate_id=estimate_id)
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
    auth: OwnerAuthContextDep,
) -> WorkOrderRead:
    try:
        return await asyncio.to_thread(
            create_work_order_from_estimate, db=db, auth=auth, estimate_id=estimate_id
        )
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
    auth: OwnerOrTechnicianAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    status_filter: Annotated[WorkOrderStatus | None, Query(alias="status")] = None,
    search: str | None = Query(default=None, max_length=120),
    customer_id: int | None = Query(default=None, ge=1),
    vehicle_id: int | None = Query(default=None, ge=1),
) -> WorkOrderListResponse:
    try:
        return await asyncio.to_thread(
            list_work_orders,
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
    auth: OwnerOrTechnicianAuthContextDep,
) -> WorkOrderRead:
    try:
        return await asyncio.to_thread(
            get_work_order, db=db, auth=auth, work_order_id=work_order_id
        )
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
    auth: OwnerAuthContextDep,
) -> WorkOrderRead:
    try:
        return await asyncio.to_thread(
            update_work_order, db=db, auth=auth, work_order_id=work_order_id, payload=payload
        )
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


@app.post("/api/work-orders/{work_order_id}/assign-technician", response_model=WorkOrderRead)
async def assign_work_order_technician_record(
    work_order_id: int,
    payload: WorkOrderAssignTechnicianRequest,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> WorkOrderRead:
    try:
        return await asyncio.to_thread(
            assign_technician, db=db, auth=auth, work_order_id=work_order_id, payload=payload
        )
    except WorkOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkOrderStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Work-order technician assignment failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Work-order storage is unavailable.",
        ) from exc


@app.post("/api/work-orders/{work_order_id}/status", response_model=WorkOrderRead)
async def update_work_order_status_record(
    work_order_id: int,
    payload: WorkOrderStatusUpdate,
    db: DbSessionDep,
    auth: OwnerOrTechnicianAuthContextDep,
) -> WorkOrderRead:
    try:
        return await asyncio.to_thread(
            transition_work_order_status,
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
    auth: OwnerOrTechnicianAuthContextDep,
) -> WorkOrderRead:
    try:
        return await asyncio.to_thread(
            add_work_order_note, db=db, auth=auth, work_order_id=work_order_id, payload=payload
        )
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


@app.get("/api/invoices", response_model=InvoiceListResponse)
async def list_invoice_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    status_filter: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
    search: str | None = Query(default=None, max_length=120),
) -> InvoiceListResponse:
    try:
        return await asyncio.to_thread(
            list_invoices,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            status=status_filter,
            search=search,
        )
    except InvoiceStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Invoice listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invoice storage is unavailable.",
        ) from exc


@app.get("/api/invoices/{invoice_id}", response_model=InvoiceRead)
async def get_invoice_record(
    invoice_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> InvoiceRead:
    try:
        return await asyncio.to_thread(get_invoice, db=db, auth=auth, invoice_id=invoice_id)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Invoice retrieval failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invoice storage is unavailable.",
        ) from exc


@app.post("/api/invoices/{invoice_id}/issue", response_model=InvoiceRead)
async def issue_invoice_record(
    invoice_id: int,
    payload: InvoiceIssueRequest,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
) -> InvoiceRead:
    try:
        return await asyncio.to_thread(
            issue_invoice,
            db=db,
            auth=auth,
            settings=settings,
            invoice_id=invoice_id,
            payload=payload,
        )
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Invoice issue failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invoice storage is unavailable.",
        ) from exc


@app.get("/api/invoices/{invoice_id}/html")
async def get_invoice_html(
    invoice_id: int,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
) -> Response:
    try:
        invoice = await asyncio.to_thread(get_invoice, db=db, auth=auth, invoice_id=invoice_id)
        return Response(
            content=await asyncio.to_thread(
                render_invoice_html, invoice, business_name=settings.business_name
            ),
            media_type="text/html; charset=utf-8",
        )
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Invoice HTML generation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invoice storage is unavailable.",
        ) from exc


@app.get("/api/invoices/{invoice_id}/pdf")
async def get_invoice_pdf(
    invoice_id: int,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
) -> Response:
    try:
        invoice = await asyncio.to_thread(get_invoice, db=db, auth=auth, invoice_id=invoice_id)
        pdf = await asyncio.to_thread(
            render_invoice_pdf, invoice, business_name=settings.business_name
        )
        headers = {"Content-Disposition": f'inline; filename="{invoice.invoice_number}.pdf"'}
        return Response(content=pdf, media_type="application/pdf", headers=headers)
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Invoice PDF generation failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invoice storage is unavailable.",
        ) from exc


@app.post("/api/invoices/{invoice_id}/payments", response_model=InvoiceRead)
async def record_invoice_payment(
    invoice_id: int,
    payload: InvoicePaymentCreate,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> InvoiceRead:
    try:
        return await asyncio.to_thread(
            record_payment, db=db, auth=auth, invoice_id=invoice_id, payload=payload
        )
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Invoice payment recording failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invoice storage is unavailable.",
        ) from exc


@app.post("/api/invoices/{invoice_id}/payments/{payment_id}/void", response_model=InvoiceRead)
async def void_invoice_payment(
    invoice_id: int,
    payment_id: int,
    payload: InvoicePaymentVoidRequest,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> InvoiceRead:
    try:
        return await asyncio.to_thread(
            void_payment,
            db=db,
            auth=auth,
            invoice_id=invoice_id,
            payment_id=payment_id,
            payload=payload,
        )
    except (InvoiceNotFoundError, PaymentNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvoiceStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Invoice payment void failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invoice storage is unavailable.",
        ) from exc


@app.post("/api/invoices/{invoice_id}/square/push", response_model=InvoiceRead)
async def push_invoice_to_square_record(
    invoice_id: int,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
) -> InvoiceRead:
    if not settings.square_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Square is not configured (sandbox only in this phase).",
        )
    client = SquareInvoiceClient(settings)
    try:
        return await asyncio.to_thread(
            lambda: push_invoice_to_square(
                db=db,
                auth=auth,
                invoice_id=invoice_id,
                client=client,
                location_id=settings.square_location_id,
            )
        )
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SquareAlreadyPushedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (SquareStoreError, InvoiceStoreError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SquareApiError as exc:
        log_security_event(
            logger,
            SecurityEventType.SQUARE_API_FAILED,
            actor_type=ActorType.USER,
            actor_id=auth.user.id,
            actor_label=auth.user.username,
            resource=f"invoice:{invoice_id}",
            invoice_id=invoice_id,
            operation="push",
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Square push failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invoice storage is unavailable.",
        ) from exc
    finally:
        client.close()


@app.post("/api/invoices/{invoice_id}/square/refresh", response_model=InvoiceRead)
async def refresh_square_invoice_record(
    invoice_id: int,
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
) -> InvoiceRead:
    if not settings.square_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Square is not configured (sandbox only in this phase).",
        )
    client = SquareInvoiceClient(settings)
    try:
        return await asyncio.to_thread(
            lambda: refresh_square_invoice(
                db=db,
                auth=auth,
                invoice_id=invoice_id,
                client=client,
            )
        )
    except InvoiceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SquareStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SquareApiError as exc:
        log_security_event(
            logger,
            SecurityEventType.SQUARE_API_FAILED,
            actor_type=ActorType.USER,
            actor_id=auth.user.id,
            actor_label=auth.user.username,
            resource=f"invoice:{invoice_id}",
            invoice_id=invoice_id,
            operation="refresh",
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Square refresh failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invoice storage is unavailable.",
        ) from exc
    finally:
        client.close()


@app.get("/api/notifications", response_model=NotificationListResponse)
async def list_notification_records(
    db: DbSessionDep,
    settings: SettingsDep,
    auth: OwnerAuthContextDep,
    page: int = Query(default=1),
    page_size: int = Query(default=20),
    unread: bool = Query(default=False),
) -> NotificationListResponse:
    try:
        return await asyncio.to_thread(
            list_notifications,
            db=db,
            auth=auth,
            settings=settings,
            page=page,
            page_size=page_size,
            unread_only=unread,
        )
    except NotificationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Notification listing failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification storage is unavailable.",
        ) from exc


@app.post("/api/notifications/{notification_id}/read", response_model=NotificationMarkReadResponse)
async def mark_notification_read_record(
    notification_id: int,
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> NotificationMarkReadResponse:
    try:
        return await asyncio.to_thread(
            mark_notification_read, db=db, auth=auth, notification_id=notification_id
        )
    except NotificationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotificationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Notification mark-read failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification storage is unavailable.",
        ) from exc


@app.post("/api/notifications/read-all", response_model=NotificationMarkReadResponse)
async def mark_all_notifications_read_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> NotificationMarkReadResponse:
    try:
        return await asyncio.to_thread(mark_all_notifications_read, db=db, auth=auth)
    except NotificationStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Notification mark-all-read failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Notification storage is unavailable.",
        ) from exc


@app.get("/api/dashboard/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> DashboardSummaryResponse:
    resolved_to = date_to or datetime.now(UTC)
    resolved_from = date_from or (resolved_to - timedelta(days=30))
    if resolved_from >= resolved_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to.")
    try:
        return await asyncio.to_thread(
            get_dashboard_summary,
            db=db,
            auth=auth,
            date_from=resolved_from,
            date_to=resolved_to,
        )
    except SQLAlchemyError as exc:
        logger.warning("Dashboard summary failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dashboard storage is unavailable.",
        ) from exc


@app.get("/api/reports/payment-activity", response_model=PaymentActivityReportResponse)
async def get_payment_activity_report_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> PaymentActivityReportResponse:
    resolved_to = date_to or datetime.now(UTC)
    resolved_from = date_from or (resolved_to - timedelta(days=30))
    if resolved_from >= resolved_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to.")
    try:
        return await asyncio.to_thread(
            get_payment_activity_report,
            db=db,
            auth=auth,
            date_from=resolved_from,
            date_to=resolved_to,
        )
    except SQLAlchemyError as exc:
        logger.warning("Payment activity report failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Report storage is unavailable.",
        ) from exc


@app.get("/api/reports/technician-time", response_model=TechnicianTimeReportResponse)
async def get_technician_time_report_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> TechnicianTimeReportResponse:
    resolved_to = date_to or datetime.now(UTC)
    resolved_from = date_from or (resolved_to - timedelta(days=30))
    if resolved_from >= resolved_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to.")
    try:
        return await asyncio.to_thread(
            get_technician_time_report,
            db=db,
            auth=auth,
            date_from=resolved_from,
            date_to=resolved_to,
        )
    except SQLAlchemyError as exc:
        logger.warning("Technician time report failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Report storage is unavailable.",
        ) from exc


@app.get("/api/reports/inventory-valuation", response_model=InventoryValuationReportResponse)
async def get_inventory_valuation_report_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
) -> InventoryValuationReportResponse:
    try:
        return await asyncio.to_thread(get_inventory_valuation_report, db=db, auth=auth)
    except SQLAlchemyError as exc:
        logger.warning("Inventory valuation report failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Report storage is unavailable.",
        ) from exc


@app.get("/api/reports/parts-usage", response_model=PartsUsageReportResponse)
async def get_parts_usage_report_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> PartsUsageReportResponse:
    resolved_to = date_to or datetime.now(UTC)
    resolved_from = date_from or (resolved_to - timedelta(days=30))
    if resolved_from >= resolved_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to.")
    try:
        return await asyncio.to_thread(
            get_parts_usage_report, db=db, auth=auth, date_from=resolved_from, date_to=resolved_to
        )
    except SQLAlchemyError as exc:
        logger.warning("Parts usage report failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Report storage is unavailable.",
        ) from exc


@app.get("/api/reports/vendor-purchasing", response_model=VendorPurchasingReportResponse)
async def get_vendor_purchasing_report_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> VendorPurchasingReportResponse:
    resolved_to = date_to or datetime.now(UTC)
    resolved_from = date_from or (resolved_to - timedelta(days=30))
    if resolved_from >= resolved_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to.")
    try:
        return await asyncio.to_thread(
            get_vendor_purchasing_report,
            db=db,
            auth=auth,
            date_from=resolved_from,
            date_to=resolved_to,
        )
    except SQLAlchemyError as exc:
        logger.warning("Vendor purchasing report failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Report storage is unavailable.",
        ) from exc


@app.get("/api/reports/work-order-cycle-time", response_model=WorkOrderCycleTimeReportResponse)
async def get_work_order_cycle_time_report_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> WorkOrderCycleTimeReportResponse:
    resolved_to = date_to or datetime.now(UTC)
    resolved_from = date_from or (resolved_to - timedelta(days=30))
    if resolved_from >= resolved_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to.")
    try:
        return await asyncio.to_thread(
            get_work_order_cycle_time_report,
            db=db,
            auth=auth,
            date_from=resolved_from,
            date_to=resolved_to,
        )
    except SQLAlchemyError as exc:
        logger.warning("Work order cycle time report failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Report storage is unavailable.",
        ) from exc


@app.get("/api/reports/diagnostic-inspection", response_model=DiagnosticInspectionReportResponse)
async def get_diagnostic_inspection_report_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> DiagnosticInspectionReportResponse:
    resolved_to = date_to or datetime.now(UTC)
    resolved_from = date_from or (resolved_to - timedelta(days=30))
    if resolved_from >= resolved_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to.")
    try:
        return await asyncio.to_thread(
            get_diagnostic_inspection_report,
            db=db,
            auth=auth,
            date_from=resolved_from,
            date_to=resolved_to,
        )
    except SQLAlchemyError as exc:
        logger.warning("Diagnostic/inspection report failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Report storage is unavailable.",
        ) from exc


# ---- Scheduling: bays ----


@app.post("/api/bays", response_model=BayRead)
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


@app.get("/api/bays", response_model=BayListResponse)
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


@app.get("/api/bays/{bay_id}", response_model=BayRead)
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


@app.patch("/api/bays/{bay_id}", response_model=BayRead)
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


@app.delete("/api/bays/{bay_id}", response_model=BayArchiveResponse)
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


# ---- Scheduling: technician working hours ----


@app.post("/api/working-hours", response_model=WorkingHoursRead)
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


@app.get("/api/working-hours", response_model=WorkingHoursListResponse)
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


@app.patch("/api/working-hours/{working_hours_id}", response_model=WorkingHoursRead)
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


@app.delete("/api/working-hours/{working_hours_id}", status_code=status.HTTP_204_NO_CONTENT)
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


# ---- Scheduling: schedule blocks ----


@app.post("/api/schedule-blocks", response_model=ScheduleBlockRead)
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


@app.get("/api/schedule-blocks", response_model=ScheduleBlockListResponse)
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


@app.get("/api/schedule-blocks/{block_id}", response_model=ScheduleBlockRead)
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


@app.patch("/api/schedule-blocks/{block_id}", response_model=ScheduleBlockRead)
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


@app.delete("/api/schedule-blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
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


# ---- Scheduling: availability ----


@app.get("/api/availability", response_model=AvailabilityResponse)
async def get_availability_record(
    db: DbSessionDep,
    auth: OwnerAuthContextDep,
    technician_id: Annotated[int, Query()],
    date_from: Annotated[datetime, Query()],
    date_to: Annotated[datetime, Query()],
    bay_id: int | None = Query(default=None),
) -> AvailabilityResponse:
    try:
        return await asyncio.to_thread(
            get_availability,
            db=db,
            auth=auth,
            technician_id=technician_id,
            date_from=date_from,
            date_to=date_to,
            bay_id=bay_id,
        )
    except SchedulingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SchedulingStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        logger.warning("Availability lookup failed due to storage error.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling storage is unavailable.",
        ) from exc


# ---- Scheduling: appointments ----


@app.post("/api/appointments", response_model=AppointmentRead)
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


@app.get("/api/appointments", response_model=AppointmentListResponse)
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


@app.get("/api/appointments/{appointment_id}", response_model=AppointmentRead)
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


@app.patch("/api/appointments/{appointment_id}", response_model=AppointmentRead)
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


@app.post("/api/appointments/{appointment_id}/move", response_model=AppointmentRead)
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


@app.post("/api/appointments/{appointment_id}/cancel", response_model=AppointmentRead)
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
