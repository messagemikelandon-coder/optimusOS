from __future__ import annotations

from app.config import Settings
from app.models import ChatRequest, ConversationMode, ResolvedLocation
from app.services.optimus_chat import OptimusChatService


class FakeResponse:
    def __init__(self, text: str, *, searched: bool = False) -> None:
        self.output_text = text
        self.output = []
        if searched:
            self.output.append(
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": [
                            {
                                "url": "https://www.autozone.com/test",
                                "title": "AutoZone test part",
                            }
                        ]
                    },
                }
            )

    def model_dump(self, mode="json"):  # type: ignore[no-untyped-def]
        return {"output": self.output}


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if len(self.calls) == 1 and "silent internal specialist" in str(kwargs["input"]).lower():
            return FakeResponse("Check voltage drop and starter command.", searched=True)
        return FakeResponse("I found the current part and labor information.", searched=True)


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_price_lookup_is_one_direct_optimus_call() -> None:
    client = FakeClient()
    service = OptimusChatService(Settings(openai_api_key="test"), client=client)
    result = service.respond(
        request=ChatRequest(
            message="Look up the price for a starter near me",
            mode=ConversationMode.AUTO,
        ),
        location=ResolvedLocation(city="Rocklin", region="CA", country="US"),
    )
    assert result.answer.startswith("I found")
    assert result.consultations == []
    assert len(client.responses.calls) == 1
    assert "reasoning" not in client.responses.calls[0]
    assert result.used_web_search is True
    assert len(result.citations) == 1


def test_complex_diagnosis_uses_silent_adviser_then_optimus() -> None:
    client = FakeClient()
    service = OptimusChatService(Settings(openai_api_key="test"), client=client)
    result = service.respond(
        request=ChatRequest(
            message="Do a deep analysis and diagnose this crank no start wiring issue",
            mode=ConversationMode.AUTO,
        )
    )
    assert result.speaker == "optimus"
    assert [item.agent for item in result.consultations] == ["diagnostic"]
    assert len(client.responses.calls) == 2
    assert all("reasoning" not in call for call in client.responses.calls)
