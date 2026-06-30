from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings
from app.models import AgentName, ChatRequest, ConversationMode, DelegationRecord


@dataclass(frozen=True, slots=True)
class ConversationPlan:
    mode: ConversationMode
    consultations: tuple[DelegationRecord, ...]
    owner_visible_speaker: str = "optimus"


_AGENT_TERMS: dict[AgentName, tuple[str, ...]] = {
    AgentName.DIAGNOSTIC: (
        "diagnose",
        "diagnostic",
        "troubleshoot",
        "no start",
        "crank no start",
        "misfire",
        "dtc",
        "fault code",
        "wiring issue",
        "parasitic draw",
        "compression",
    ),
    AgentName.ESTIMATOR: (
        "estimate",
        "quote",
        "labor time",
        "book time",
        "how much should i charge",
        "price the job",
    ),
    AgentName.PARTS: (
        "part number",
        "parts store",
        "in stock",
        "availability",
        "fitment",
        "interchange",
        "o'reilly",
        "autozone",
        "napa",
        "rockauto",
    ),
    AgentName.SERVICE_ADVISOR: (
        "customer complaint",
        "explain to customer",
        "client update",
        "recommend repair",
        "declined repair",
    ),
    AgentName.OPERATIONS: (
        "schedule",
        "workflow",
        "dispatch",
        "capacity",
        "inventory process",
        "business process",
    ),
    AgentName.DOCUMENTATION: (
        "invoice",
        "work order",
        "inspection report",
        "service record",
        "final invoice",
    ),
    AgentName.MARKETING: (
        "facebook post",
        "instagram post",
        "marketing",
        "advertisement",
        "social media",
        "flyer",
    ),
    AgentName.COMPLIANCE: (
        "legal",
        "compliance",
        "liability",
        "warranty law",
        "tax law",
        "regulation",
    ),
    AgentName.QUALITY_CONTROL: (
        "quality check",
        "double check",
        "verify the repair",
        "comeback prevention",
        "post repair inspection",
    ),
}

# Optimus owns these capabilities directly. These should not trigger another agent merely
# because the user asks for a price, availability, labor time, or an estimate.
_OPTIMUS_NATIVE_TERMS = (
    "look up price",
    "lookup price",
    "find price",
    "parts price",
    "local parts",
    "labor time",
    "book time",
    "job estimate",
    "estimate this job",
    "availability at",
    "in stock near",
)

_EXPLICIT_TEAM_TERMS = (
    "ask the agents",
    "consult the agents",
    "consult the team",
    "use the team",
    "have the agents",
    "/team",
)

_EXPLICIT_DIRECT_TERMS = (
    "talk to me directly",
    "just you",
    "do not ask the agents",
    "don't ask the agents",
    "no agents",
    "/direct",
)

_COMPLEXITY_TERMS = (
    "deep analysis",
    "root cause",
    "step by step diagnosis",
    "audit",
    "review everything",
    "full report",
    "compare options",
    "build a plan",
)


class OptimusConversationRouter:
    """Routes owner messages while keeping Optimus as the only visible speaker."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def plan(self, request: ChatRequest) -> ConversationPlan:
        text = self._normalize(request.message)
        requested = self._dedupe(request.requested_agents)

        if request.mode == ConversationMode.DIRECT or self._contains_any(text, _EXPLICIT_DIRECT_TERMS):
            return ConversationPlan(mode=ConversationMode.DIRECT, consultations=())

        if not self._settings.agent_delegation_enabled:
            return ConversationPlan(mode=ConversationMode.DIRECT, consultations=())

        if requested:
            return ConversationPlan(
                mode=request.mode,
                consultations=tuple(
                    DelegationRecord(agent=agent, reason="Explicitly requested by the owner.")
                    for agent in requested[: self._settings.max_agent_consultations]
                ),
            )

        matched = self._match_agents(text)
        explicit_team = request.mode == ConversationMode.TEAM or self._contains_any(
            text, _EXPLICIT_TEAM_TERMS
        )

        if explicit_team:
            team_agents = matched or [
                AgentName.DIAGNOSTIC, AgentName.ESTIMATOR, AgentName.PARTS
            ]
            return ConversationPlan(
                mode=ConversationMode.TEAM,
                consultations=tuple(
                    DelegationRecord(agent=agent, reason="Owner requested team consultation.")
                    for agent in team_agents[: self._settings.max_agent_consultations]
                ),
            )

        # Price, parts availability, labor time, and estimates are native Optimus work.
        # He should use internet tools directly instead of consulting the team first.
        if self._contains_any(text, _OPTIMUS_NATIVE_TERMS):
            return ConversationPlan(mode=ConversationMode.DIRECT, consultations=())

        if request.mode == ConversationMode.AUTO:
            auto_consultations = self._auto_select(text, matched)
            return ConversationPlan(
                mode=ConversationMode.AUTO,
                consultations=tuple(
                    auto_consultations[: self._settings.max_agent_consultations]
                ),
            )

        return ConversationPlan(mode=ConversationMode.DIRECT, consultations=())

    def _auto_select(
        self,
        text: str,
        matched: list[AgentName],
    ) -> list[DelegationRecord]:
        if not matched:
            return []

        complexity = self._contains_any(text, _COMPLEXITY_TERMS)
        high_value_specialists = {
            AgentName.DIAGNOSTIC,
            AgentName.COMPLIANCE,
            AgentName.DOCUMENTATION,
            AgentName.MARKETING,
        }

        selected: list[DelegationRecord] = []
        for agent in matched:
            if agent in high_value_specialists or complexity:
                selected.append(
                    DelegationRecord(
                        agent=agent,
                        reason=self._reason_for(agent),
                    )
                )

        # Avoid consulting agents for ordinary conversation or simple single-domain requests.
        if len(selected) == 1 and not complexity and selected[0].agent == AgentName.DIAGNOSTIC:
            diagnostic_hits = sum(term in text for term in _AGENT_TERMS[AgentName.DIAGNOSTIC])
            if diagnostic_hits < 2:
                return []
        return selected

    @staticmethod
    def _reason_for(agent: AgentName) -> str:
        reasons = {
            AgentName.DIAGNOSTIC: "Complex diagnostic reasoning benefits from a silent specialist review.",
            AgentName.ESTIMATOR: "Detailed pricing or labor calculation benefits from estimator review.",
            AgentName.PARTS: "Fitment or sourcing complexity benefits from parts review.",
            AgentName.SERVICE_ADVISOR: "Customer-facing repair communication benefits from service-advisor review.",
            AgentName.OPERATIONS: "Operational planning benefits from workflow review.",
            AgentName.DOCUMENTATION: "Formal business records benefit from documentation review.",
            AgentName.MARKETING: "Published promotional content benefits from marketing review.",
            AgentName.COMPLIANCE: "Legal or compliance exposure benefits from risk review.",
            AgentName.QUALITY_CONTROL: "Repair verification benefits from quality-control review.",
        }
        return reasons[agent]

    @staticmethod
    def _match_agents(text: str) -> list[AgentName]:
        return [agent for agent, terms in _AGENT_TERMS.items() if any(term in text for term in terms)]

    @staticmethod
    def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.casefold()).strip()

    @staticmethod
    def _dedupe(values: list[AgentName]) -> list[AgentName]:
        return list(dict.fromkeys(values))
