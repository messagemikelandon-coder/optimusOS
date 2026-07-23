"""API tests for the Phase 2B platform-support-only operational summary.

Covers authorization (support only; owner/manager/technician/suspended-owner/
unauthenticated/impersonated-owner denied), bounded collection (TTL cache,
repeated calls do not re-probe), that the reused Phase 2A storage snapshot is
never re-collected by this endpoint (no Docker subprocess), Cache-Control:
no-store, non-leakage of sensitive values, capability-counter surfacing, the
throttled degraded warning, rate limiting, and the additive OpenAPI contract.
Runtime collection is injected via monkeypatch, so nothing here touches a real
Postgres/Redis/Docker.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.main as main
from app.auth import hash_password, require_support_context
from app.db import get_db_session, get_settings
from app.db_models import Shop, ShopMembership, UserAccount
from app.operations_monitor import storage_service
from app.runtime_metrics import request_metrics
from app.runtime_monitor import (
    DependencySnapshot,
    DependencyStatus,
    QueueSnapshot,
    QueueStatus,
    RuntimeSignals,
    WorkerHeartbeatSnapshot,
    WorkerHeartbeatStatus,
    runtime_service,
)
from app.storage_monitor import (
    DiskUsage,
    DockerAvailability,
    DockerStorage,
    StorageSnapshot,
)

_SUPPORT_CREDS = {"username": "support-one", "password": "support-password-123"}
_OWNER_CREDS = {"username": "owner", "password": "owner-password-123"}


@pytest.fixture(autouse=True)
def _reset_services():
    runtime_service.reset()
    storage_service.reset()
    request_metrics.reset()
    yield
    runtime_service.reset()
    storage_service.reset()
    request_metrics.reset()


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


def _signals(
    *,
    postgres=DependencyStatus.REACHABLE,
    redis=DependencyStatus.REACHABLE,
    worker=WorkerHeartbeatStatus.ALIVE,
    worker_age=12.0,
    queue=QueueStatus.NOT_CONFIGURED,
    depth=None,
) -> RuntimeSignals:
    return RuntimeSignals(
        dependencies=DependencySnapshot(postgres=postgres, redis=redis),
        worker=WorkerHeartbeatSnapshot(status=worker, age_seconds=worker_age, ttl_seconds=150),
        queue=QueueSnapshot(status=queue, depth=depth),
    )


def _stub_runtime(monkeypatch, signals: RuntimeSignals):
    """Inject runtime collection so no real Postgres/Redis is touched. Returns a
    counter list whose length is the number of actual collections."""
    calls: list[int] = []

    def _collect(**_kwargs) -> RuntimeSignals:
        calls.append(1)
        return signals

    monkeypatch.setattr(main, "collect_runtime_signals", _collect)
    return calls


def _stub_storage_collect(monkeypatch, snapshot: StorageSnapshot | None):
    """Track whether the summary ever launches a storage (Docker) collection.
    It must not: the summary reuses the cache and never re-collects."""
    calls: list[int] = []

    def _collect(_path: str) -> StorageSnapshot:
        calls.append(1)
        assert snapshot is not None
        return snapshot

    monkeypatch.setattr(main, "collect_storage_snapshot", _collect)
    return calls


def _storage_snapshot(used_percent: float = 40.0) -> StorageSnapshot:
    return StorageSnapshot(
        disk=DiskUsage(
            path="/",
            total_bytes=100,
            used_bytes=int(used_percent),
            available_bytes=100 - int(used_percent),
            used_percent=used_percent,
        ),
        docker=DockerStorage(
            availability=DockerAvailability.UNAVAILABLE, reason="x", categories=()
        ),
    )


def _login(client, creds) -> None:
    assert client.post("/api/auth/login", json=creds).status_code == 200


# --- authorization: unit gate -------------------------------------------------


@pytest.mark.parametrize("role", ["owner", "manager", "technician"])
def test_gate_rejects_non_support_roles(role: str, db_session) -> None:
    from datetime import UTC, datetime, timedelta

    from app.auth import AuthContext
    from app.db_models import AuthSession

    user = UserAccount(username=f"{role}-x", role=role)
    session = AuthSession(
        user_id=1,
        token_hash="t",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_seen_at=datetime.now(UTC),
    )
    with pytest.raises(Exception) as exc_info:
        require_support_context(db_session, AuthContext(user=user, session=session))
    assert getattr(exc_info.value, "status_code", None) == 403


# --- authorization: real HTTP -------------------------------------------------


def test_support_can_read_summary(settings, db_session, monkeypatch) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_runtime(monkeypatch, _signals())
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        response = client.get("/api/operations/summary")
        assert response.status_code == 200
        body = response.json()
        assert body["scope"] == "application_process"
        assert body["freshness"] == "fresh"
        assert body["dependencies"]["postgres"] == "reachable"
        assert body["worker"]["status"] == "alive"
        assert body["worker"]["age_seconds"] == 12.0
        assert body["queue"]["status"] == "not_configured"
        assert body["queue"]["depth"] is None
        assert body["storage"]["status"] == "not_collected"
        assert set(body["capabilities"]["decisions"]) == {
            "would_allow",
            "would_deny",
            "resolution_error",
        }
        # The request-traffic block reflects real in-process requests (login + this
        # GET both flowed through the metrics middleware).
        assert body["requests"]["total_requests"] >= 1
        assert "status_classes" in body["requests"]
    finally:
        main.app.dependency_overrides.clear()


def test_owner_is_denied(settings, db_session, monkeypatch) -> None:
    _stub_runtime(monkeypatch, _signals())
    try:
        client = _client(settings, db_session)
        _login(client, _OWNER_CREDS)
        assert client.get("/api/operations/summary").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


@pytest.mark.parametrize("role", ["manager", "technician"])
def test_manager_and_technician_denied_via_http(
    role: str, settings, db_session, monkeypatch
) -> None:
    _make_member(db_session, username=f"{role}-one", role=role, password=f"{role}-password-123")
    _stub_runtime(monkeypatch, _signals())
    try:
        client = _client(settings, db_session)
        _login(client, {"username": f"{role}-one", "password": f"{role}-password-123"})
        assert client.get("/api/operations/summary").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_suspended_owner_denied_via_http(settings, db_session, monkeypatch) -> None:
    shop = db_session.scalars(select(Shop)).first()
    assert shop is not None
    shop.status = "suspended"
    db_session.add(shop)
    db_session.commit()
    _stub_runtime(monkeypatch, _signals())
    try:
        client = _client(settings, db_session)
        _login(client, _OWNER_CREDS)
        assert client.get("/api/operations/summary").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_impersonated_owner_session_denied_via_http(settings, db_session, monkeypatch) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    shop = db_session.scalars(select(Shop)).first()
    assert shop is not None
    _stub_runtime(monkeypatch, _signals())
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        impersonate = client.post(f"/api/support/shops/{shop.id}/impersonate")
        assert impersonate.status_code == 200  # cookie now carries an owner session
        assert client.get("/api/operations/summary").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_unauthenticated_is_denied(settings, db_session, monkeypatch) -> None:
    _stub_runtime(monkeypatch, _signals())
    try:
        client = _client(settings, db_session)
        assert client.get("/api/operations/summary").status_code == 401
    finally:
        main.app.dependency_overrides.clear()


# --- Cache-Control ------------------------------------------------------------


def test_response_sets_cache_control_no_store(settings, db_session, monkeypatch) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_runtime(monkeypatch, _signals())
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        response = client.get("/api/operations/summary")
        assert response.headers.get("cache-control") == "no-store"
    finally:
        main.app.dependency_overrides.clear()


# --- bounded collection -------------------------------------------------------


def test_repeated_requests_within_ttl_do_not_reprobe(settings, db_session, monkeypatch) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    calls = _stub_runtime(monkeypatch, _signals())
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        freshness = []
        for _ in range(5):
            r = client.get("/api/operations/summary")
            assert r.status_code == 200
            freshness.append(r.json()["freshness"])
        assert len(calls) == 1  # one probe/read pass within the TTL window
        assert freshness[0] == "fresh"
        assert all(f == "cached" for f in freshness[1:])
    finally:
        main.app.dependency_overrides.clear()


# --- storage is reused, never re-collected ------------------------------------


def test_summary_never_collects_storage(settings, db_session, monkeypatch) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_runtime(monkeypatch, _signals())
    storage_calls = _stub_storage_collect(monkeypatch, _storage_snapshot())
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        body = client.get("/api/operations/summary").json()
        # No storage snapshot has been collected yet, and the summary must not
        # launch one itself -- it reports not_collected and never runs Docker.
        assert body["storage"]["status"] == "not_collected"
        assert len(storage_calls) == 0
    finally:
        main.app.dependency_overrides.clear()


def test_summary_reuses_already_collected_storage(settings, db_session, monkeypatch) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_runtime(monkeypatch, _signals())
    storage_calls = _stub_storage_collect(monkeypatch, _storage_snapshot(used_percent=95.0))
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        # Populate the storage cache via the dedicated endpoint (one collection).
        assert client.get("/api/operations/storage").status_code == 200
        assert len(storage_calls) == 1
        body = client.get("/api/operations/summary").json()
        assert body["storage"]["status"] == "collected"
        assert body["storage"]["disk_status"] == "critical"  # 95% >= critical 90
        assert body["storage"]["docker_availability"] == "unavailable"
        # The summary reused the cache -- still exactly one storage collection.
        assert len(storage_calls) == 1
    finally:
        main.app.dependency_overrides.clear()


# --- capability counters surfaced ---------------------------------------------


def test_capability_counters_are_surfaced(settings, db_session, monkeypatch) -> None:
    from app.capability_metrics import capability_metrics

    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_runtime(monkeypatch, _signals())
    capability_metrics.reset()
    capability_metrics.record("would_allow")
    capability_metrics.record("would_deny")
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        body = client.get("/api/operations/summary").json()
        assert body["capabilities"]["decisions"]["would_allow"] >= 1
        assert body["capabilities"]["decisions"]["would_deny"] >= 1
        assert body["capabilities"]["total"] >= 2
    finally:
        main.app.dependency_overrides.clear()
        capability_metrics.reset()


# --- throttled degraded warning -----------------------------------------------


def test_degraded_emits_one_warning_event(settings, db_session, monkeypatch, caplog) -> None:
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_runtime(monkeypatch, _signals(postgres=DependencyStatus.UNREACHABLE))
    try:
        client = _client(settings, db_session)
        _login(client, _SUPPORT_CREDS)
        with caplog.at_level(logging.WARNING, logger="optimus"):
            for _ in range(4):
                assert client.get("/api/operations/summary").status_code == 200
        events = [
            r for r in caplog.records if getattr(r, "reliability_event", None) == "runtime.degraded"
        ]
        assert len(events) == 1
        assert events[0].actor_role == "support"
        assert isinstance(events[0].actor_user_id, int)
        assert events[0].postgres_status == "unreachable"
    finally:
        main.app.dependency_overrides.clear()


# --- non-leakage --------------------------------------------------------------


def test_no_sensitive_values_in_body_or_logs(settings, db_session, monkeypatch, caplog) -> None:
    # The real database/redis URLs contain host/credential-shaped substrings; a
    # degraded snapshot must expose none of them in the body or any log record.
    hardened = settings.model_copy(
        update={
            "database_url": "postgresql://secret-user:secret-pass@pg-host:5432/db",
            "redis_url": "redis://redis-host:6379/0",
            "worker_queue_redis_key": "secret-queue-key",
        }
    )
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_runtime(
        monkeypatch,
        _signals(postgres=DependencyStatus.UNREACHABLE, worker=WorkerHeartbeatStatus.MISSING),
    )
    try:
        client = _client(hardened, db_session)
        _login(client, _SUPPORT_CREDS)
        with caplog.at_level(logging.WARNING, logger="optimus"):
            response = client.get("/api/operations/summary")
        assert response.status_code == 200
        for needle in ("secret-user", "secret-pass", "pg-host", "redis-host", "secret-queue-key"):
            assert needle not in response.text
            for record in caplog.records:
                assert needle not in record.getMessage()
                assert all(needle not in str(v) for v in record.__dict__.values())
    finally:
        main.app.dependency_overrides.clear()


# --- rate limiting ------------------------------------------------------------


def test_endpoint_is_rate_limited(settings, db_session, monkeypatch) -> None:
    limited = settings.model_copy(update={"max_operations_summary_requests_per_minute": 1})
    _make_user(db_session, username="support-one", role="support", password="support-password-123")
    _stub_runtime(monkeypatch, _signals())
    try:
        client = _client(limited, db_session)
        _login(client, _SUPPORT_CREDS)
        assert client.get("/api/operations/summary").status_code == 200
        assert client.get("/api/operations/summary").status_code == 429
    finally:
        main.app.dependency_overrides.clear()


# --- additive OpenAPI ---------------------------------------------------------


def test_summary_openapi_is_additive_only() -> None:
    schema = main.app.openapi()
    paths = schema["paths"]
    assert "/api/operations/summary" in paths
    op = paths["/api/operations/summary"]["get"]
    assert "OperationsSummaryRead" in op["responses"]["200"]["content"]["application/json"][
        "schema"
    ].get("$ref", "")
    # Pre-existing surfaces unchanged.
    assert "get" in paths["/api/operations/storage"]
    assert set(paths["/api/bays"].keys()) >= {"get", "post"}
    assert "get" in paths["/health"]
    assert "get" in paths["/ready"]
