from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.models import DecodedVehicle, VehicleInput
from app.services.http import SafeHttpClient

VPIC_BASE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues"


def _first_nonblank(*values: Any) -> str | None:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


class VinService:
    def __init__(self, http: SafeHttpClient) -> None:
        self._http = http

    async def decode(self, vehicle: VehicleInput) -> DecodedVehicle:
        if not vehicle.vin:
            return DecodedVehicle(**vehicle.model_dump())

        url = f"{VPIC_BASE_URL}/{quote(vehicle.vin, safe='')}"
        payload = await self._http.get_json(url, params={"format": "json"})
        results = payload.get("Results") or []
        if not results:
            raise ValueError("NHTSA returned no VIN result.")
        item = results[0]

        displacement = _first_nonblank(item.get("DisplacementL"))
        cylinders = _first_nonblank(item.get("EngineCylinders"))
        engine_model = _first_nonblank(item.get("EngineModel"), item.get("EngineConfiguration"))
        engine_parts = []
        if displacement:
            engine_parts.append(f"{displacement}L")
        if cylinders:
            engine_parts.append(f"{cylinders}-cyl")
        if engine_model:
            engine_parts.append(engine_model)

        decoded_year: int | None = None
        model_year = _first_nonblank(item.get("ModelYear"))
        if model_year and model_year.isdigit():
            decoded_year = int(model_year)

        return DecodedVehicle(
            vin=vehicle.vin,
            year=vehicle.year or decoded_year,
            make=vehicle.make or _first_nonblank(item.get("Make")),
            model=vehicle.model or _first_nonblank(item.get("Model")),
            trim=vehicle.trim or _first_nonblank(item.get("Trim"), item.get("Series")),
            engine=vehicle.engine or (" ".join(engine_parts) if engine_parts else None),
            drivetrain=vehicle.drivetrain or _first_nonblank(item.get("DriveType")),
            body_class=_first_nonblank(item.get("BodyClass")),
            error_code=_first_nonblank(item.get("ErrorCode")),
            error_text=_first_nonblank(item.get("ErrorText")),
        )
