from __future__ import annotations

from app.config import Settings
from app.control import OptimusConversationRouter
from app.models import AgentName, ChatRequest, ConversationMode


def router() -> OptimusConversationRouter:
    return OptimusConversationRouter(
        Settings(openai_api_key="test", max_agent_consultations=3)
    )


def test_price_lookup_stays_direct_to_optimus() -> None:
    plan = router().plan(
        ChatRequest(
            message="Look up the price and local availability for a starter near me",
            mode=ConversationMode.AUTO,
        )
    )
    assert plan.consultations == ()
    assert plan.owner_visible_speaker == "optimus"


def test_explicit_direct_mode_never_consults_agents() -> None:
    plan = router().plan(
        ChatRequest(
            message="Diagnose this crank no start and wiring issue",
            mode=ConversationMode.DIRECT,
        )
    )
    assert plan.consultations == ()


def test_auto_mode_consults_diagnostic_for_complex_diagnosis() -> None:
    plan = router().plan(
        ChatRequest(
            message="Do a deep analysis and diagnose this crank no start with a wiring issue",
            mode=ConversationMode.AUTO,
        )
    )
    assert [item.agent for item in plan.consultations] == [AgentName.DIAGNOSTIC]


def test_requested_agent_is_used_but_optimus_remains_speaker() -> None:
    plan = router().plan(
        ChatRequest(
            message="Review this",
            requested_agents=[AgentName.QUALITY_CONTROL],
        )
    )
    assert [item.agent for item in plan.consultations] == [AgentName.QUALITY_CONTROL]
    assert plan.owner_visible_speaker == "optimus"


def test_team_mode_uses_relevant_agents_with_limit() -> None:
    plan = OptimusConversationRouter(
        Settings(openai_api_key="test", max_agent_consultations=2)
    ).plan(
        ChatRequest(
            message="Consult the team about diagnosis, parts fitment, and an estimate",
            mode=ConversationMode.TEAM,
        )
    )
    assert len(plan.consultations) == 2
