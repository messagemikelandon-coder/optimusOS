"""API tests for the Phase 2A platform-support-only storage endpoint.

Covers authorization (support only; owner/manager/technician/suspended-owner/
unauthenticated/impersonated-owner denied), bounded collection (TTL cache,
repeated calls do not re-collect), the throttled warning event, Cache-Control:
no-store, non-leakage of the raw configured path, rate limiting, and the
additive OpenAPI contract. Host/Docker collection is injected via monkeypatch,
so nothing here touches the real machine.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.main as main
from app.auth import AuthContext, hash_password, require_support_context
from app.db import get_db_session, get_settings
from app.db_models import AuthSession, Shop, ShopMembership, UserAccount
from app.operations_monitor import storage_service
from app.storage_monitor import (
    DiskUsage,
    DockerAvailability,
    DockerCategoryUsage,
    DockerStorage,
    StorageSnapshot,
)

_SUPPORT_CREDS = {"username": "support-one", "password": "support-password-123"}
_OWNER_CREDS = {"username": "owner", "password": "owner-password-123"}


@pytest.fixture(autouse=True)
def _reset_storage_service():
    storage_service.reset()
    yield
    storage_service.reset()


def _make_user(db_session, *, username: str, role: str, password: str) -> UserAccount:
    user = UserAccount(
        username=username,
        display_name=username.title(),
        role=role,
        password_hash=hash_password(password),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _make_member(db_session, *, username: str, role: str, password: str) -> UserAccount:
    # A manager/technician can only log in with an active ShopMembership matching
    # its role (Phase 3 membership-boundary rule), so create one on the
    # bootstrap owner's shop -- mirroring tests/test_role_isolation.py.
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    shop_id = db_session.scalar(
        select(ShopMembership.shop_id).where(
            ShopMembership.user_account_id == owner.id,
            ShopMembership.role == "owner",
            ShopMembership.is_active.is_(True),
        )
    )
    assert shop_id is not None
    user = UserAccount(
        username=username,
        display_name=username.title(),
        role=role,
        shop_owner_id=owner.id if role == "technician" else None,
        password_hash=hash_password(password),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    db_session.add(ShopMembership(shop_id=shop_id, user_account_id=user.id, role=role))
    db_session.commit()
    return user


def _client(settings, db_session) -> TestClient:
    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    return TestClient(main.app)


def _snapshot(*, used_percent: float | None, path: str = "/", docker: DockerStorage | None = None):
    return StorageSnapshot(
        disk=DiskUsage(
            path=path,
            total_bytes=100,
            used_bytes=None if used_percent is None else int(used_percent),
            available_bytes=None,
            used_percent=used_percent,
        ),
        docker=docker
        or DockerStorage(
            availability=DockerAvailability.AVAILABLE,
            reason=None,
            categories=(
                DockerCategoryUsage(
                    category="images", count=2, size_bytes=1_500_000_000, reclaimable_bytes=0
                ),
                DockerCategoryUsage(
                    category="containers", count=1, size_bytes=120, reclaimable_bytes=0
                ),
                DockerCategoryUsage(
                    category="volumes", count=2, size_bytes=50, reclaimable_bytes=0
                ),
                DockerCategoryUsage(
                    category="build_cache", count=5, size_bytes=200, reclaimable_bytes=200
                ),
            ),
        ),
    )


def _stub_collect(monkeypatch, snapshot: StorageSnapshot):
    """Inject collection so no real Docker/disk is touched. Returns a counter
    list whose length is the number of actual collections."""
    calls: list[int] = []

    def _collect(_path: str) -> StorageSnapshot:
        calls.append(1)
        return snapshot

    monkeypatch.setattr(main, "collect_storage_snapshot", _collect)
    return calls


def _login(client, creds) -> None:
    assert client.post("/api/auth/login", json=creds).status_code == 200


# --- authorization: unit gate (support only) ----------------------------------


def _auth(role: str, *, impersonated_by: int | None = None) -> AuthContext:
    user = UserAccount(username=f"{role}-x", role=role)
    session = AuthSession(
        user_id=1,
        token_hash="t",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_seen_at=datetime.now(UTC),
        impersonated_by_user_account_id=impersonated_by,
    )
    return AuthContext(user=user, session=session)


@pytest.mark.parametrize("role", ["owner", "manager", "technician"])
def test_gate_rejects_non_support_roles(role: str, db_session) -> None:
    with pytest.raises(Exception) as exc_info:
        require_support_context(db_session, _auth(role))
    assert getattr(exc_info.value, "status_code", None) == 403


def test_gate_rejects_impersonated_owner_session(db_session) -> None:
    # Support impersonation mints a real session whose user role is "owner";
    # such a session must not reach this platform-infrastructure endpoint.
    imp = _auth("owner", impersonated_by=999)
    with pytest.raises(Exception) as exc_info:
        require_support_context(db_session, imp)
    assert getattr(exc_info.value, "status_code", None) == 403


def test_gate_rejects_owner_regardless_of_suspension(db_session) -> None:
    # A suspended-shop owner is still role "owner" and is denied for the same
    # reason a healthy owner is: this endpoint is support-only, never shop-scoped.
    with pytest.raises(Exception) as exc_info:
        require_support_context(db_session, _auth("owner"))
    assert getattr(exc_info.value, "status_code", None) == 403


# --- authorization: real HTTP -------------------------------------------------


def test_support_can_read_storage(settings, db_session, monkeypatch) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_collect(monkeypatch, _snapshot(used_percent=42.0))
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        response = client.get("/api/operations/storage")
        assert response.status_code == 200
        body = response.json()
        assert body["target"] == "application_filesystem"
        # Cache was reset by the autouse fixture, so the first request collects.
        assert body["freshness"] == "fresh"
        assert body["age_seconds"] == 0.0
        assert "collected_at" in body and isinstance(body["age_seconds"], (int, float))
        assert body["disk"]["used_percent"] == 42.0
        assert body["disk"]["status"] == "ok"
        assert "path" not in body["disk"]
        assert body["docker"]["availability"] == "available"
    finally:
        main.app.dependency_overrides.clear()


def test_owner_is_denied(settings, db_session, monkeypatch) -> None:
    _stub_collect(monkeypatch, _snapshot(used_percent=42.0))
    try:
        client = _client(settings, db_session)
        _login(client, _OWNER_CREDS)
        assert client.get("/api/operations/storage").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


@pytest.mark.parametrize("role", ["manager", "technician"])
def test_manager_and_technician_are_denied_via_http(
    role: str, settings, db_session, monkeypatch
) -> None:
    _make_member(db_session, username=f"{role}-one", role=role, password=f"{role}-password-123")
    _stub_collect(monkeypatch, _snapshot(used_percent=42.0))
    try:
        client = _client(settings, db_session)
        _login(client, {"username": f"{role}-one", "password": f"{role}-password-123"})
        assert client.get("/api/operations/storage").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_suspended_owner_is_denied_via_http(settings, db_session, monkeypatch) -> None:
    # A genuinely suspended-shop owner (Shop.status = "suspended") is still role
    # "owner"; the support-only gate denies it, with no suspension bypass.
    shop = db_session.scalars(select(Shop)).first()
    assert shop is not None
    shop.status = "suspended"
    db_session.add(shop)
    db_session.commit()
    _stub_collect(monkeypatch, _snapshot(used_percent=42.0))
    try:
        client = _client(settings, db_session)
        _login(client, _OWNER_CREDS)
        assert client.get("/api/operations/storage").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_impersonated_owner_session_is_denied_via_http(settings, db_session, monkeypatch) -> None:
    # Full flow: support logs in, impersonates the shop owner (the response
    # switches the session cookie to a real owner-role session), then hits the
    # endpoint -- which must reject the impersonated-owner session.
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    shop = db_session.scalars(select(Shop)).first()
    assert shop is not None
    _stub_collect(monkeypatch, _snapshot(used_percent=42.0))
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        impersonate = client.post(f"/api/support/shops/{shop.id}/impersonate")
        assert impersonate.status_code == 200  # cookie now carries an owner session
        assert client.get("/api/operations/storage").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_unauthenticated_is_denied(settings, db_session, monkeypatch) -> None:
    _stub_collect(monkeypatch, _snapshot(used_percent=42.0))
    try:
        client = _client(settings, db_session)
        assert client.get("/api/operations/storage").status_code == 401
    finally:
        main.app.dependency_overrides.clear()


# --- Cache-Control ------------------------------------------------------------


def test_response_sets_cache_control_no_store(settings, db_session, monkeypatch) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_collect(monkeypatch, _snapshot(used_percent=42.0))
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        response = client.get("/api/operations/storage")
        assert response.headers.get("cache-control") == "no-store"
    finally:
        main.app.dependency_overrides.clear()


# --- bounded collection: repeated calls do not re-collect ---------------------


def test_repeated_requests_within_ttl_do_not_recollect(settings, db_session, monkeypatch) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    calls = _stub_collect(monkeypatch, _snapshot(used_percent=42.0))
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        freshness = []
        for _ in range(5):
            r = client.get("/api/operations/storage")
            assert r.status_code == 200
            freshness.append(r.json()["freshness"])
        # Real monotonic elapsed here is well under the default 30s TTL, so
        # exactly one Docker collection happens: the first request is fresh and
        # every subsequent one is served from cache (no re-collection).
        assert len(calls) == 1
        assert freshness[0] == "fresh"
        assert all(f == "cached" for f in freshness[1:])
    finally:
        main.app.dependency_overrides.clear()


# --- throttled warning event --------------------------------------------------


def test_critical_usage_emits_one_warning_event_then_dedupes(
    settings, db_session, monkeypatch, caplog
) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_collect(monkeypatch, _snapshot(used_percent=95.0))
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        with caplog.at_level(logging.WARNING, logger="optimus"):
            for _ in range(4):
                assert client.get("/api/operations/storage").status_code == 200
        events = [
            r
            for r in caplog.records
            if getattr(r, "reliability_event", None) == "disk.usage_critical"
        ]
        # Repeated GETs in the same critical state produce exactly one event
        # (the requirement). At the HTTP level the TTL cache already bounds this
        # to one fresh collection within the window; the emit-throttle itself
        # (transition/cooldown dedup across multiple fresh collections) is
        # isolated and proven in tests/test_operations_monitor.py.
        assert len(events) == 1
        assert events[0].actor_role == "support"
        assert events[0].storage_target == "application_filesystem"
        # Actor is identified by internal id, never username/email.
        assert isinstance(events[0].actor_user_id, int)
    finally:
        main.app.dependency_overrides.clear()


# --- docker unavailable surfaced ----------------------------------------------


def test_docker_unavailable_is_reported(settings, db_session, monkeypatch) -> None:
    unavailable = DockerStorage(
        availability=DockerAvailability.UNAVAILABLE,
        reason="docker CLI is not installed or not on PATH",
        categories=(),
    )
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_collect(monkeypatch, _snapshot(used_percent=10.0, docker=unavailable))
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        body = client.get("/api/operations/storage").json()
        assert body["docker"]["availability"] == "unavailable"
        assert body["docker"]["reason"]
        assert body["docker"]["categories"] == []
    finally:
        main.app.dependency_overrides.clear()


# --- non-leakage of the raw configured path -----------------------------------


def test_configured_raw_path_never_appears_in_response_or_logs(
    settings, db_session, monkeypatch, caplog
) -> None:
    secret_path = "/srv/private/customer-secrets/pg-data"
    hardened = settings.model_copy(update={"disk_monitor_path": secret_path})
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    # Snapshot carries the sensitive path internally AND is critical (so a
    # warning is also emitted) -- neither the body nor the log may leak it.
    _stub_collect(monkeypatch, _snapshot(used_percent=96.0, path=secret_path))
    try:
        client = _client(hardened, db_session)
        _login(client, _SUPPORT_CREDS)
        with caplog.at_level(logging.WARNING, logger="optimus"):
            response = client.get("/api/operations/storage")
        assert response.status_code == 200
        assert secret_path not in response.text
        assert "customer-secrets" not in response.text
        assert response.json()["target"] == "application_filesystem"
        # And not in any emitted log record (message or any field value).
        for record in caplog.records:
            assert secret_path not in record.getMessage()
            assert all(secret_path not in str(v) for v in record.__dict__.values())
    finally:
        main.app.dependency_overrides.clear()


# --- rate limiting ------------------------------------------------------------


def test_endpoint_is_rate_limited(settings, db_session, monkeypatch) -> None:
    limited = settings.model_copy(update={"max_operations_storage_requests_per_minute": 1})
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_collect(monkeypatch, _snapshot(used_percent=42.0))
    try:
        client = _client(limited, db_session)
        _login(client, _SUPPORT_CREDS)
        assert client.get("/api/operations/storage").status_code == 200
        assert client.get("/api/operations/storage").status_code == 429
    finally:
        main.app.dependency_overrides.clear()


# --- additive OpenAPI ---------------------------------------------------------


def test_storage_openapi_is_additive_only() -> None:
    schema = main.app.openapi()
    paths = schema["paths"]
    assert "/api/operations/storage" in paths
    assert "get" in paths["/api/operations/storage"]
    op = paths["/api/operations/storage"]["get"]
    assert "StorageObservabilityRead" in op["responses"]["200"]["content"]["application/json"][
        "schema"
    ].get("$ref", "")
    # Pre-existing surfaces unchanged.
    assert set(paths["/api/bays"].keys()) >= {"get", "post"}
    assert "get" in paths["/api/support/shops"]
    assert "get" in paths["/health"]
    assert "get" in paths["/ready"]
