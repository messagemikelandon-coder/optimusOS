from __future__ import annotations

import httpx
import pytest

from app.models import VehicleInput, VinDecodeStatus
from app.services.vin import VinService

_GOOD_VIN = "2C3CDXGJ6LH120446"


class FakeHttp:
    async def get_json(self, url: str, params=None):  # type: ignore[no-untyped-def]
        return {
            "Results": [
                {
                    "ModelYear": "2020",
                    "Make": "DODGE",
                    "Model": "Charger",
                    "Trim": "Scat Pack",
                    "DisplacementL": "6.4",
                    "EngineCylinders": "8",
                    "DriveType": "RWD/Rear-Wheel Drive",
                    "BodyClass": "Sedan/Saloon",
                    "ErrorCode": "0",
                    "ErrorText": "0 - VIN decoded clean. Check Digit (9th position) is correct",
                }
            ]
        }


class RaisingHttp:
    """Simulates an unreachable upstream (e.g. egress blocked / NHTSA down)."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def get_json(self, url: str, params=None):  # type: ignore[no-untyped-def]
        raise self._exc


class EmptyResultsHttp:
    async def get_json(self, url: str, params=None):  # type: ignore[no-untyped-def]
        return {"Results": [{"ErrorCode": "11", "ErrorText": "Incomplete VIN"}]}


class MalformedShapeHttp:
    """Upstream returned valid JSON but not the expected object shape.

    ``payload`` is whatever NHTSA sent instead of a ``{"Results": [ {...} ]}``
    object (e.g. a bare list, a string, or a list where the first result is not a
    dict). The safe-failure entry point must degrade to UNAVAILABLE rather than
    raising ``AttributeError`` and surfacing a 5xx.
    """

    def __init__(self, payload: object) -> None:
        self._payload = payload

    async def get_json(self, url: str, params=None):  # type: ignore[no-untyped-def]
        return self._payload


@pytest.mark.asyncio
async def test_decodes_vin() -> None:
    decoded = await VinService(FakeHttp()).decode(  # type: ignore[arg-type]
        VehicleInput(vin=_GOOD_VIN)
    )
    assert decoded.year == 2020
    assert decoded.make == "DODGE"
    assert decoded.model == "Charger"
    assert decoded.engine and "6.4L" in decoded.engine


def test_rejects_path_injection_vin() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VehicleInput(vin="2C3CDXGJ6LH/../../")


@pytest.mark.asyncio
async def test_decode_intake_returns_decoded() -> None:
    result = await VinService(FakeHttp()).decode_intake(_GOOD_VIN)  # type: ignore[arg-type]
    assert result.status is VinDecodeStatus.DECODED
    assert result.decoded is not None
    assert result.decoded.make == "DODGE"
    assert result.decoded.model == "Charger"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("timed out"),
        httpx.HTTPStatusError(
            "500", request=httpx.Request("GET", "https://x"), response=httpx.Response(500)
        ),
        ValueError("Expected JSON response, received text/html"),
    ],
)
async def test_decode_intake_is_unavailable_on_upstream_failure(exc: Exception) -> None:
    # Safe-failure: any transport/parse error degrades to UNAVAILABLE, never raises.
    result = await VinService(RaisingHttp(exc)).decode_intake(_GOOD_VIN)  # type: ignore[arg-type]
    assert result.status is VinDecodeStatus.UNAVAILABLE
    assert result.decoded is None
    assert "manually" in result.message.lower()


@pytest.mark.asyncio
async def test_decode_intake_unavailable_when_nothing_resolves() -> None:
    # An upstream response that resolves no identity fields must not be presented
    # as a confirmed vehicle.
    result = await VinService(EmptyResultsHttp()).decode_intake(_GOOD_VIN)  # type: ignore[arg-type]
    assert result.status is VinDecodeStatus.UNAVAILABLE
    assert result.decoded is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        ["Results", "not-a-dict"],  # top-level list instead of an object
        "unexpected string body",  # top-level string
        {"Results": ["not-a-dict-item"]},  # first result is not an object
    ],
)
async def test_decode_intake_unavailable_on_malformed_upstream_shape(payload: object) -> None:
    # Safe-failure: a JSON body of an unexpected shape must degrade to UNAVAILABLE
    # rather than raising AttributeError and surfacing a 5xx.
    result = await VinService(MalformedShapeHttp(payload)).decode_intake(  # type: ignore[arg-type]
        _GOOD_VIN
    )
    assert result.status is VinDecodeStatus.UNAVAILABLE
    assert result.decoded is None
