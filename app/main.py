from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.auth import require_access_token
from app.config import Settings, get_settings
from app.errors import EstimatorResearchError
from app.models import (
    ChatRequest,
    ChatResponse,
    EstimateRequest,
    EstimateResponse,
    LocationInput,
    ResolvedLocation,
)
from app.orchestrator import OptimusResearchOrchestrator
from app.rate_limit import RateLimitExceeded, SlidingWindowRateLimiter
from app.services.http import SafeHttpClient
from app.services.location import LocationService
from app.services.optimus_chat import OptimusChatService

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger("optimus")
STATIC_DIR = Path(__file__).parent / "static"
SettingsDep = Annotated[Settings, Depends(get_settings)]

app = FastAPI(
    title="Optimus Command Center | Landon Motor Works",
    version=__version__,
    docs_url="/docs",
    redoc_url=None,
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
    }


@app.post(
    "/api/location/resolve",
    response_model=ResolvedLocation,
    dependencies=[Depends(require_access_token)],
)
async def resolve_location(
    location: LocationInput,
    settings: SettingsDep,
) -> ResolvedLocation:
    return await location_service(settings).resolve(location)


@app.post(
    "/api/chat",
    response_model=ChatResponse,
    dependencies=[Depends(require_access_token)],
)
async def chat(
    payload: ChatRequest,
    request_context: Request,
    settings: SettingsDep,
) -> ChatResponse:
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
    dependencies=[Depends(require_access_token)],
)
async def estimate(
    request: EstimateRequest,
    request_context: Request,
    settings: SettingsDep,
) -> EstimateResponse:
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
