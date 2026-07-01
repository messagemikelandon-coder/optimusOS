from __future__ import annotations

import json
import random
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pydantic import HttpUrl

from app.config import Settings
from app.control import OptimusConversationRouter
from app.models import Availability, ChatRequest, Confidence, ConversationMode, PartOption
from app.security import UnsafeUrlError, approval_for_action, validate_https_url
from app.services.estimator import choose_part

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures" / "research_cases.json"


def money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def estimate_backtest() -> int:
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    checks = 0
    for case in cases:
        for _ in range(1000):
            labor_rate = random.uniform(50, 250)
            supplies_pct = random.uniform(0, 10)
            tax_pct = random.uniform(0, 12)
            mobile_fee = random.uniform(0, 150)
            labor = money(case["hours"] * labor_rate)
            supplies = money(labor * supplies_pct / 100)
            tax = money(case["parts"] * tax_pct / 100)
            total = money(labor + case["parts"] + supplies + tax + mobile_fee)
            assert total >= labor
            assert total >= case["parts"]
            assert all(value >= 0 for value in (labor, supplies, tax, total))
            checks += 1
    return checks


def routing_backtest() -> int:
    router = OptimusConversationRouter(Settings(openai_api_key="test", max_agent_consultations=2))
    price_phrases = [
        "look up price",
        "find price",
        "parts price",
        "local parts",
        "labor time",
        "book time",
        "job estimate",
        "in stock near",
    ]
    vehicles = ["Honda Civic", "Dodge Challenger", "Nissan Frontier", "Chevy Malibu"]
    checks = 0
    for _ in range(5000):
        phrase = random.choice(price_phrases)
        vehicle = random.choice(vehicles)
        plan = router.plan(
            ChatRequest(message=f"{phrase} for a {vehicle}", mode=ConversationMode.AUTO)
        )
        assert plan.consultations == ()
        assert plan.owner_visible_speaker == "optimus"
        checks += 1

    for _ in range(2500):
        plan = router.plan(
            ChatRequest(
                message="deep analysis diagnose crank no start wiring issue",
                mode=ConversationMode.DIRECT,
            )
        )
        assert plan.consultations == ()
        checks += 1
    return checks


def authority_backtest() -> int:
    checks = 0
    for _ in range(2500):
        assert (
            approval_for_action(random.choice(["search", "lookup_price", "estimate"])).required
            is False
        )
        assert approval_for_action("edit_code", origin="owner").required is False
        assert (
            approval_for_action(
                "send_message", origin="owner", explicit_owner_instruction=True
            ).required
            is False
        )
        assert approval_for_action("purchase", origin="owner").required is True
        assert (
            approval_for_action("purchase", origin="owner", current_turn_confirmation=True).required
            is False
        )
        checks += 5
    return checks


def estimator_selection_backtest() -> int:
    availability_values = [value for value in Availability if value != Availability.OUT_OF_STOCK]
    confidence_values = list(Confidence)
    confidence_rank = {Confidence.HIGH: 0, Confidence.MEDIUM: 1, Confidence.LOW: 2}
    availability_rank = {
        Availability.CONFIRMED_IN_STOCK: 0,
        Availability.LIMITED: 1,
        Availability.UNKNOWN: 2,
        Availability.ONLINE_ONLY: 3,
        Availability.OUT_OF_STOCK: 4,
    }
    checks = 0
    for index in range(20_000):
        options = [
            PartOption(
                retailer=f"Retailer {candidate}",
                unit_price=random.uniform(1, 5000),
                availability=random.choice(availability_values),
                url=HttpUrl(f"https://example.com/{index}/{candidate}"),
                confidence=random.choice(confidence_values),
            )
            for candidate in range(3)
        ]
        selected = choose_part(options)
        assert selected is not None
        expected = min(
            options,
            key=lambda option: (
                confidence_rank[option.confidence],
                availability_rank[option.availability],
                option.unit_price,
                10_000,
            ),
        )
        assert selected is expected
        checks += 1
    return checks


def url_security_backtest() -> int:
    blocked = (
        "http://example.com/part",
        "https://127.0.0.1/private",
        "https://localhost/private",
        "file:///etc/passwd",
    )
    checks = 0
    for index in range(4000):
        candidate = blocked[index % len(blocked)]
        try:
            validate_https_url(candidate)
        except UnsafeUrlError:
            checks += 1
        else:
            raise AssertionError(f"Unsafe URL was accepted: {candidate}")
    return checks


def main() -> None:
    estimate_checks = estimate_backtest()
    routing_checks = routing_backtest()
    authority_checks = authority_backtest()
    selection_checks = estimator_selection_backtest()
    url_checks = url_security_backtest()
    total = estimate_checks + routing_checks + authority_checks + selection_checks + url_checks
    print(
        "Regression backtest passed: "
        f"{estimate_checks} estimate math, {routing_checks} routing, "
        f"{authority_checks} authority, {selection_checks} part-selection, "
        f"{url_checks} URL-security checks ({total} total)"
    )


if __name__ == "__main__":
    main()
