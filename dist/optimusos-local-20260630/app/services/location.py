from __future__ import annotations

from typing import Any

from app.models import LocationInput, ResolvedLocation
from app.services.http import SafeHttpClient

CENSUS_COORDINATES_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"


def _first_item(mapping: dict[str, list[dict[str, Any]]], *names: str) -> dict[str, Any] | None:
    lowered = {key.lower(): value for key, value in mapping.items()}
    for name in names:
        values = lowered.get(name.lower())
        if values:
            return values[0]
    return None


def _string(item: dict[str, Any] | None, *keys: str) -> str | None:
    if not item:
        return None
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


class LocationService:
    def __init__(self, http: SafeHttpClient) -> None:
        self._http = http

    async def resolve(self, location: LocationInput) -> ResolvedLocation:
        if not location.coordinates:
            return ResolvedLocation(
                city=location.city,
                region=location.region,
                postal_code=location.postal_code,
                country=location.country,
                timezone=location.timezone,
                source="user",
            )

        coordinates = location.coordinates
        try:
            payload = await self._http.get_json(
                CENSUS_COORDINATES_URL,
                params={
                    "x": coordinates.longitude,
                    "y": coordinates.latitude,
                    "benchmark": "Public_AR_Current",
                    "vintage": "Current_Current",
                    "format": "json",
                    "layers": "all",
                },
            )
            geographies = payload.get("result", {}).get("geographies", {})
            place = _first_item(
                geographies,
                "Incorporated Places",
                "Census Designated Places",
                "County Subdivisions",
            )
            state = _first_item(geographies, "States")
            zip_area = _first_item(
                geographies,
                "Zip Code Tabulation Areas",
                "ZIP Code Tabulation Areas",
                "2020 Census ZIP Code Tabulation Areas",
            )

            return ResolvedLocation(
                city=location.city or _string(place, "NAME", "BASENAME"),
                region=location.region or _string(state, "STUSAB", "NAME"),
                postal_code=location.postal_code or _string(zip_area, "ZCTA5", "GEOID", "BASENAME"),
                country=location.country,
                timezone=location.timezone,
                latitude=round(coordinates.latitude, 3),
                longitude=round(coordinates.longitude, 3),
                accuracy_m=coordinates.accuracy_m,
                source="census_coordinates",
            )
        except Exception:
            # Location resolution failure must not expose or persist exact coordinates elsewhere.
            return ResolvedLocation(
                city=location.city,
                region=location.region,
                postal_code=location.postal_code,
                country=location.country,
                timezone=location.timezone,
                latitude=round(coordinates.latitude, 3),
                longitude=round(coordinates.longitude, 3),
                accuracy_m=coordinates.accuracy_m,
                source="partial",
            )
