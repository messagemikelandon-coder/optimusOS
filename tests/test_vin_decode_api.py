"""API tests for the vehicle-first standalone VIN decode intake endpoint
(`POST /api/vehicles/decode-vin`).

Covers authentication (owner/manager gated), the decoded happy path, the
safe-failure `unavailable` path (HTTP 200, not a 5xx), invalid-VIN rejection,
the `Cache-Control: no-store` header, and per-client rate limiting. The VIN
service is injected via a dependency override, so nothing here makes a real
outbound NHTSA call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.db import get_db_session, get_settings
from app.models import DecodedVehicle, VinDecodeResponse, VinDecodeStatus

pytestmark = pytest.mark.anyio

_OWNER_CREDS = {"username": "owner", "password": "owner-password-123"}
_VALID_VIN = "2C3CDXGJ6LH120446"


class FakeVinService:
    def __init__(self, response: VinDecodeResponse) -> None:
        self._response = response
        self.calls: list[str] = []

    async def decode_intake(self, vin: str) -> VinDecodeResponse:
        self.calls.append(vin)
        return self._response


def _client(settings, db_session) -> TestClient:
    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    return TestClient(main.app)


def _use_vin_service(response: VinDecodeResponse) -> FakeVinService:
    fake = FakeVinService(response)
    main.app.dependency_overrides[main.get_vin_service] = lambda: fake
    return fake


def _login(client, creds) -> None:
    assert client.post("/api/auth/login", json=creds).status_code == 200


def _decoded_response() -> VinDecodeResponse:
    return VinDecodeResponse(
        status=VinDecodeStatus.DECODED,
        message="VIN decoded. Review the populated fields before saving.",
        decoded=DecodedVehicle(
            vin=_VALID_VIN, year=2020, make="DODGE", model="Charger", trim="Scat Pack"
        ),
    )


def test_requires_authenticated_session(settings, db_session) -> None:
    _use_vin_service(_decoded_response())
    try:
        client = _client(settings, db_session)
        response = client.post("/api/vehicles/decode-vin", json={"vin": _VALID_VIN})
        assert response.status_code == 401
    finally:
        main.app.dependency_overrides.clear()


def test_owner_decodes_vin(settings, db_session) -> None:
    fake = _use_vin_service(_decoded_response())
    try:
        client = _client(settings, db_session)
        _login(client, _OWNER_CREDS)
        response = client.post("/api/vehicles/decode-vin", json={"vin": _VALID_VIN.lower()})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "decoded"
        assert body["decoded"]["make"] == "DODGE"
        assert body["decoded"]["model"] == "Charger"
        # VIN is normalized to upper-case before the lookup.
        assert fake.calls == [_VALID_VIN]
        assert response.headers.get("cache-control") == "no-store"
    finally:
        main.app.dependency_overrides.clear()


def test_unavailable_is_soft_failure(settings, db_session) -> None:
    _use_vin_service(
        VinDecodeResponse(
            status=VinDecodeStatus.UNAVAILABLE,
            message="VIN lookup is unavailable right now. Enter the vehicle details manually.",
            decoded=None,
        )
    )
    try:
        client = _client(settings, db_session)
        _login(client, _OWNER_CREDS)
        response = client.post("/api/vehicles/decode-vin", json={"vin": _VALID_VIN})
        # Safe failure: a 200 with a manual-entry message, never a 5xx.
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["decoded"] is None
    finally:
        main.app.dependency_overrides.clear()


@pytest.mark.parametrize("bad_vin", ["SHORT", "2C3CDXGJ6LH1204460000", "2C3CDXGJ6LH12044I"])
def test_invalid_vin_rejected(settings, db_session, bad_vin: str) -> None:
    _use_vin_service(_decoded_response())
    try:
        client = _client(settings, db_session)
        _login(client, _OWNER_CREDS)
        response = client.post("/api/vehicles/decode-vin", json={"vin": bad_vin})
        assert response.status_code == 422
    finally:
        main.app.dependency_overrides.clear()


def test_endpoint_is_rate_limited(settings, db_session) -> None:
    limited = settings.model_copy(update={"max_vin_decode_requests_per_minute": 1})
    _use_vin_service(_decoded_response())
    try:
        client = _client(limited, db_session)
        _login(client, _OWNER_CREDS)
        assert client.post("/api/vehicles/decode-vin", json={"vin": _VALID_VIN}).status_code == 200
        assert client.post("/api/vehicles/decode-vin", json={"vin": _VALID_VIN}).status_code == 429
    finally:
        main.app.dependency_overrides.clear()
