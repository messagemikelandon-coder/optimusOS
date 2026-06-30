from __future__ import annotations

import pytest

from app.models import Coordinates, LocationInput
from app.services.location import LocationService


class FakeHttp:
    async def get_json(self, url: str, params=None):  # type: ignore[no-untyped-def]
        return {
            "result": {
                "geographies": {
                    "Incorporated Places": [{"NAME": "Junction City"}],
                    "States": [{"STUSAB": "KS", "NAME": "Kansas"}],
                    "Zip Code Tabulation Areas": [{"ZCTA5": "66441"}],
                }
            }
        }


@pytest.mark.asyncio
async def test_resolves_coordinates() -> None:
    result = await LocationService(FakeHttp()).resolve(  # type: ignore[arg-type]
        LocationInput(coordinates=Coordinates(latitude=39.03, longitude=-96.83))
    )
    assert result.city == "Junction City"
    assert result.region == "KS"
    assert result.postal_code == "66441"
    assert result.source == "census_coordinates"
