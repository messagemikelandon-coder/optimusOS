from __future__ import annotations

import asyncio

from app.config import Settings
from app.models import (
    ChatRequest,
    ChatResponse,
    EstimateRequest,
    EstimateResponse,
    ResolvedLocation,
)
from app.orchestrator import OptimusResearchOrchestrator
from app.security import ApprovalDecision, approval_for_action
from app.services.http import SafeHttpClient
from app.services.location import LocationService
from app.services.optimus_chat import OptimusChatService


class OptimusInternetSkill:
    """Owner-facing Optimus skill with direct chat, internet research, and estimates."""

    name = "optimus_owner_control"
    version = "7.0.1"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._orchestrator = OptimusResearchOrchestrator(self.settings)

    async def estimate_job(self, payload: dict[str, object]) -> dict[str, object]:
        request = EstimateRequest.model_validate(payload)
        response: EstimateResponse = await self._orchestrator.estimate_job(request)
        return response.model_dump(mode="json")

    async def chat(self, payload: dict[str, object]) -> dict[str, object]:
        request = ChatRequest.model_validate(payload)
        resolved_location: ResolvedLocation | None = None
        if request.location is not None:
            http = SafeHttpClient(
                timeout_seconds=self.settings.http_timeout_seconds,
                allowed_hosts=("geocoding.geo.census.gov",),
            )
            resolved_location = await LocationService(http).resolve(request.location)
        service = OptimusChatService(self.settings)
        response: ChatResponse = await asyncio.to_thread(
            service.respond,
            request=request,
            location=resolved_location,
        )
        return response.model_dump(mode="json")

    def approval_policy(
        self,
        action: str,
        *,
        origin: str = "owner",
        explicit_owner_instruction: bool = False,
        current_turn_confirmation: bool = False,
        optimus_authorized: bool = False,
    ) -> ApprovalDecision:
        return approval_for_action(
            action,
            origin=origin,
            explicit_owner_instruction=explicit_owner_instruction,
            current_turn_confirmation=current_turn_confirmation,
            optimus_authorized=optimus_authorized,
            autonomy_mode=self.settings.autonomy_mode,
        )
