from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.models import (
    DecodedVehicle,
    VehicleInput,
    VinDecodeResponse,
    VinDecodeStatus,
)
from app.services.http import SafeHttpClient

logger = logging.getLogger(__name__)

VPIC_BASE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues"

_UNAVAILABLE_MESSAGE = (
    "VIN lookup is unavailable right now. Enter the vehicle details manually; "
    "you can retry the decode later."
)


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

    async def decode_intake(self, vin: str) -> VinDecodeResponse:
        """Decode a VIN for standalone vehicle intake, never raising on an
        unreachable or malformed upstream response.

        This is the vehicle-first, safe-failure entry point used by the intake
        endpoint. Any transport error, non-JSON body, empty result, or unexpected
        upstream shape degrades to a ``VinDecodeStatus.UNAVAILABLE`` result with a
        manual-entry message rather than a 5xx -- the shop can always fall back to
        typing the vehicle in by hand. A VIN that decodes but resolves neither
        year, make, nor model is also reported as ``UNAVAILABLE`` so an
        un-decoded VIN is never presented as a confirmed vehicle.
        """
        try:
            decoded = await self.decode(VehicleInput(vin=vin))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "VIN decode unavailable",
                extra={
                    "reliability_event": "vin_decode.unavailable",
                    "error_type": type(exc).__name__,
                },
            )
            return VinDecodeResponse(
                status=VinDecodeStatus.UNAVAILABLE, message=_UNAVAILABLE_MESSAGE, decoded=None
            )

        has_year_make_model = bool(decoded.year and decoded.make and decoded.model)
        has_any = bool(
            decoded.year or decoded.make or decoded.model or decoded.trim or decoded.engine
        )
        if has_year_make_model:
            return VinDecodeResponse(
                status=VinDecodeStatus.DECODED,
                message="VIN decoded. Review the populated fields before saving.",
                decoded=decoded,
            )
        if has_any:
            return VinDecodeResponse(
                status=VinDecodeStatus.PARTIAL,
                message=(
                    "VIN partially decoded. Confirm and complete the vehicle details before saving."
                ),
                decoded=decoded,
            )
        return VinDecodeResponse(
            status=VinDecodeStatus.UNAVAILABLE, message=_UNAVAILABLE_MESSAGE, decoded=None
        )
