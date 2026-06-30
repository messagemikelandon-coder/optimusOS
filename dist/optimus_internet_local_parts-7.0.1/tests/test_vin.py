from __future__ import annotations

import pytest

from app.models import VehicleInput
from app.services.vin import VinService


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


@pytest.mark.asyncio
async def test_decodes_vin() -> None:
    decoded = await VinService(FakeHttp()).decode(  # type: ignore[arg-type]
        VehicleInput(vin="2C3CDXGJ6LH120446")
    )
    assert decoded.year == 2020
    assert decoded.make == "DODGE"
    assert decoded.model == "Charger"
    assert decoded.engine and "6.4L" in decoded.engine


def test_rejects_path_injection_vin() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VehicleInput(vin="2C3CDXGJ6LH/../../")
