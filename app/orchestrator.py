from __future__ import annotations

import asyncio

from app.config import Settings
from app.models import EstimateRequest, EstimateResponse
from app.services.estimator import EstimateService
from app.services.http import SafeHttpClient
from app.services.location import LocationService
from app.services.openai_web import OpenAIWebResearchService
from app.services.vin import VinService


class OptimusResearchOrchestrator:
    """Read-only research workflow. It performs no purchase, booking, or messaging action."""

    def __init__(self, settings: Settings) -> None:
        outbound_hosts = (
            "vpic.nhtsa.dot.gov",
            "geocoding.geo.census.gov",
        )
        http = SafeHttpClient(
            timeout_seconds=settings.http_timeout_seconds,
            allowed_hosts=outbound_hosts,
        )
        self._location = LocationService(http)
        self._vin = VinService(http)
        self._research = OpenAIWebResearchService(settings)
        self._estimate = EstimateService(settings)

    async def estimate_job(self, request: EstimateRequest) -> EstimateResponse:
        # The AI research path requires a location (parts availability / store
        # distance depend on it). `EstimateRequest.location` is optional only so
        # the deterministic Job Compiler release path can build a location-less
        # estimate without going through this orchestrator; that path never
        # calls estimate_job. Guard defensively.
        if request.location is None:
            raise ValueError("An estimate location is required for AI research.")
        location_task = asyncio.create_task(self._location.resolve(request.location))
        vehicle_task = asyncio.create_task(self._vin.decode(request.vehicle))
        location, vehicle = await asyncio.gather(location_task, vehicle_task)

        # The OpenAI Python SDK call is synchronous. Offload it so FastAPI's event loop stays responsive.
        research = await asyncio.to_thread(
            self._research.research,
            vehicle=vehicle,
            job=request.job,
            location=location,
        )
        return self._estimate.build(
            request=request,
            vehicle=vehicle,
            location=location,
            research=research,
        )
