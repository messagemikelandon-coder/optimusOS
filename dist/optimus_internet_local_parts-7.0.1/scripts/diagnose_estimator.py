from __future__ import annotations

import asyncio

from app.config import Settings
from app.errors import EstimatorResearchError
from app.models import EstimateRequest
from app.openai_key_info import read_project_key, validate_key_text
from app.orchestrator import OptimusResearchOrchestrator


async def run_diagnostic() -> None:
    key_info = read_project_key()
    problems = validate_key_text(key_info.value)
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}")
        raise SystemExit(1)

    settings = Settings(openai_api_key=key_info.value)
    print("Optimus estimator diagnostic")
    print(f"Key fingerprint: {key_info.fingerprint}")
    print(f"Primary estimator model: {settings.estimator_model}")
    print(f"Fallback model: {settings.openai_fallback_model or 'disabled'}")
    print(f"Search context: {settings.web_search_context_size}")
    print("Running one live labor-and-parts test. This uses API credits.")

    request = EstimateRequest.model_validate(
        {
            "vehicle": {"year": 2018, "make": "Honda", "model": "CR-V", "engine": "1.5L"},
            "job": "Replace front brake pads and rotors",
            "location": {"postal_code": "95677", "country": "US"},
            "labor_rate": 100,
            "mobile_service_fee": 0,
            "shop_supplies_percent": 0,
            "parts_tax_rate": 0,
        }
    )

    try:
        result = await OptimusResearchOrchestrator(settings).estimate_job(request)
    except EstimatorResearchError as exc:
        print("RESULT: FAILED")
        print(f"Code: {exc.code}")
        print(f"Stage: {exc.stage}")
        print(f"Request ID: {exc.request_id}")
        print(f"Message: {exc.message}")
        raise SystemExit(2) from exc
    except Exception as exc:
        print("RESULT: FAILED")
        print(f"Unexpected local error: {type(exc).__name__}: {exc}")
        raise SystemExit(3) from exc

    print("RESULT: PASSED")
    print(f"Research request ID: {result.research.request_id or 'not returned'}")
    print(f"Research mode: {result.research.research_mode or 'standard'}")
    print(f"Vehicle: {result.vehicle.display_name()}")
    print(f"Labor hours: {result.totals.labor_hours}")
    print(f"Selected priced parts: {len(result.selected_parts)}")
    print(f"Source links: {len(result.research.citations)}")
    print(f"Estimated total: ${result.totals.estimated_total:.2f}")
    for warning in result.research.warnings:
        print(f"WARNING: {warning}")


def main() -> None:
    asyncio.run(run_diagnostic())


if __name__ == "__main__":
    main()
