from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.config import Settings
from app.db import get_db_session, get_settings
from app.db_models import UserAccount

pytestmark = pytest.mark.anyio


def _client_with_overrides(settings: Settings, db_session: Session) -> TestClient:
    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    return TestClient(main.app)


def _clear_overrides() -> None:
    main.app.dependency_overrides.clear()


def test_synthetic_provisioning_disabled_by_default(
    settings: Settings, db_session: Session
) -> None:
    """The base test settings fixture already has app_env="test" (not
    production), but the explicit provisioning flag defaults to False -- the
    flag alone must be sufficient to keep this off in every real deployment
    that doesn't set it, including local dev and CI by default."""
    assert settings.optimus_test_account_provisioning is False
    client = _client_with_overrides(settings, db_session)
    try:
        response = client.post("/api/test-support/synthetic-owner")
        assert response.status_code == 404
    finally:
        _clear_overrides()


def test_synthetic_provisioning_disabled_when_app_env_is_production(
    settings: Settings, db_session: Session
) -> None:
    """Even with the flag on, a production app_env is an independent, equally
    required guard -- neither condition alone is sufficient."""
    prod_settings = settings.model_copy(
        update={"optimus_test_account_provisioning": True, "app_env": "production"}
    )
    client = _client_with_overrides(prod_settings, db_session)
    try:
        response = client.post("/api/test-support/synthetic-owner")
        assert response.status_code == 404
    finally:
        _clear_overrides()


def test_synthetic_owner_provisioning_creates_a_real_working_account(
    settings: Settings, db_session: Session
) -> None:
    enabled_settings = settings.model_copy(update={"optimus_test_account_provisioning": True})
    client = _client_with_overrides(enabled_settings, db_session)
    try:
        response = client.post("/api/test-support/synthetic-owner")
        assert response.status_code == 200
        body = response.json()
        assert body["role"] == "owner"
        assert body["technician_id"] is None
        assert len(body["password"]) >= 16

        user = db_session.get(UserAccount, body["user_id"])
        assert user is not None
        assert user.username == body["username"]
        assert user.role == "owner"
        assert user.is_synthetic_test_account is True

        # The returned credentials must work through the real login flow --
        # not a bypass, a real POST to the real endpoint.
        login_response = client.post(
            "/api/auth/login",
            json={"username": body["username"], "password": body["password"]},
        )
        assert login_response.status_code == 200
        assert login_response.json()["user"]["role"] == "owner"
    finally:
        _clear_overrides()


def test_synthetic_technician_provisioning_creates_a_real_working_account(
    settings: Settings, db_session: Session
) -> None:
    enabled_settings = settings.model_copy(update={"optimus_test_account_provisioning": True})
    client = _client_with_overrides(enabled_settings, db_session)
    try:
        owner_response = client.post("/api/test-support/synthetic-owner")
        assert owner_response.status_code == 200
        owner_username = owner_response.json()["username"]

        tech_response = client.post(
            "/api/test-support/synthetic-technician",
            json={"owner_username": owner_username},
        )
        assert tech_response.status_code == 200
        body = tech_response.json()
        assert body["role"] == "technician"
        assert body["technician_id"] is not None

        user = db_session.get(UserAccount, body["user_id"])
        assert user is not None
        assert user.role == "technician"
        assert user.is_synthetic_test_account is True

        login_response = client.post(
            "/api/auth/login",
            json={"username": body["username"], "password": body["password"]},
        )
        assert login_response.status_code == 200
        assert login_response.json()["user"]["role"] == "technician"
    finally:
        _clear_overrides()


def test_synthetic_technician_rejects_non_synthetic_owner(
    settings: Settings, db_session: Session
) -> None:
    """A caller cannot attach a synthetic technician to the real bootstrapped
    owner (or any other real owner account), even by supplying its exact,
    valid username."""
    enabled_settings = settings.model_copy(update={"optimus_test_account_provisioning": True})
    client = _client_with_overrides(enabled_settings, db_session)
    try:
        response = client.post(
            "/api/test-support/synthetic-technician",
            json={"owner_username": settings.optimus_owner_username},
        )
        assert response.status_code == 422
    finally:
        _clear_overrides()


def test_cleanup_deletes_synthetic_owner_and_cascades_technician(
    settings: Settings, db_session: Session
) -> None:
    enabled_settings = settings.model_copy(update={"optimus_test_account_provisioning": True})
    client = _client_with_overrides(enabled_settings, db_session)
    try:
        owner_body = client.post("/api/test-support/synthetic-owner").json()
        tech_body = client.post(
            "/api/test-support/synthetic-technician",
            json={"owner_username": owner_body["username"]},
        ).json()

        delete_response = client.delete(
            f"/api/test-support/synthetic-accounts/{owner_body['user_id']}"
        )
        assert delete_response.status_code == 204

        assert db_session.get(UserAccount, owner_body["user_id"]) is None
        assert db_session.get(UserAccount, tech_body["user_id"]) is None
    finally:
        _clear_overrides()


def test_cleanup_deletes_owner_with_scheduling_data(
    settings: Settings, db_session: Session
) -> None:
    """Regression test for a real bug found while adding
    tests/e2e/test_scheduling_concurrency.py: `appointments.customer_id`/
    `vehicle_id`/`technician_id` are deliberately `ON DELETE RESTRICT` (an
    appointment must never silently vanish or lose its audit trail if a
    customer/vehicle/technician is later removed in real usage, which only
    ever archives those records). `_delete_owner_and_dependents` hard-deletes
    them directly, so it must delete Appointments first -- SQLite (used by
    this fast test) doesn't enforce the FK, so this test can't reproduce the
    real `ForeignKeyViolation` that only appeared against real Postgres, but
    it does pin the fix's actual behavior: the appointment row is gone after
    cleanup, not left orphaned."""
    enabled_settings = settings.model_copy(update={"optimus_test_account_provisioning": True})
    client = _client_with_overrides(enabled_settings, db_session)
    try:
        owner_body = client.post("/api/test-support/synthetic-owner").json()
        login_response = client.post(
            "/api/auth/login",
            json={"username": owner_body["username"], "password": owner_body["password"]},
        )
        assert login_response.status_code == 200

        customer = client.post(
            "/api/customers", json={"first_name": "Sched", "last_name": "Regress"}
        ).json()
        vehicle = client.post(
            f"/api/customers/{customer['id']}/vehicles",
            json={"make": "Ford", "model": "F-150"},
        ).json()
        technician = client.post(
            "/api/technicians", json={"first_name": "Regress", "last_name": "Tech"}
        ).json()
        appointment = client.post(
            "/api/appointments",
            json={
                "customer_id": customer["id"],
                "vehicle_id": vehicle["id"],
                "technician_id": technician["id"],
                "service_type": "Regression check",
                "start_time": "2030-01-01T09:00:00Z",
                "end_time": "2030-01-01T10:00:00Z",
            },
        ).json()
        assert "id" in appointment

        delete_response = client.delete(
            f"/api/test-support/synthetic-accounts/{owner_body['user_id']}"
        )
        assert delete_response.status_code == 204
        assert db_session.get(UserAccount, owner_body["user_id"]) is None

        from app.db_models import Appointment

        assert db_session.get(Appointment, appointment["id"]) is None
    finally:
        _clear_overrides()


def test_cleanup_refuses_to_delete_non_synthetic_account(
    settings: Settings, db_session: Session
) -> None:
    """This can never be turned into a way to delete a real account, even by
    guessing or iterating over ids."""
    enabled_settings = settings.model_copy(update={"optimus_test_account_provisioning": True})
    client = _client_with_overrides(enabled_settings, db_session)
    try:
        real_owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
        assert real_owner is not None

        response = client.delete(f"/api/test-support/synthetic-accounts/{real_owner.id}")
        assert response.status_code == 404
        assert db_session.get(UserAccount, real_owner.id) is not None
    finally:
        _clear_overrides()


def test_sweep_cleanup_deletes_all_synthetic_owners_only(
    settings: Settings, db_session: Session
) -> None:
    enabled_settings = settings.model_copy(update={"optimus_test_account_provisioning": True})
    client = _client_with_overrides(enabled_settings, db_session)
    try:
        client.post("/api/test-support/synthetic-owner")
        client.post("/api/test-support/synthetic-owner")

        response = client.delete("/api/test-support/synthetic-accounts")
        assert response.status_code == 200
        assert response.json()["deleted_count"] == 2

        remaining_synthetic = db_session.scalar(
            select(UserAccount).where(UserAccount.is_synthetic_test_account.is_(True))
        )
        assert remaining_synthetic is None

        real_owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
        assert real_owner is not None
    finally:
        _clear_overrides()
