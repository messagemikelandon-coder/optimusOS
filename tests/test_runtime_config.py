"""Validation of the Phase 2B runtime-observability settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_heartbeat_ttl_below_interval_is_rejected() -> None:
    # A TTL shorter than the write interval would let a live worker's key expire
    # between beats and read as "missing"; reject at startup.
    with pytest.raises(ValidationError):
        Settings(worker_heartbeat_interval_seconds=60, worker_heartbeat_ttl_seconds=30)


def test_heartbeat_ttl_equal_to_interval_is_rejected() -> None:
    # `ttl == interval` is NOT enough: the real write-to-write gap is `interval`
    # plus the worker loop's dependency-probe overhead, so the key would lapse
    # each cycle. The validator requires `ttl >= 2 * interval`.
    with pytest.raises(ValidationError):
        Settings(worker_heartbeat_interval_seconds=30, worker_heartbeat_ttl_seconds=30)


def test_heartbeat_ttl_just_below_twice_interval_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(worker_heartbeat_interval_seconds=30, worker_heartbeat_ttl_seconds=59)


def test_heartbeat_ttl_at_twice_interval_is_allowed() -> None:
    settings = Settings(worker_heartbeat_interval_seconds=30, worker_heartbeat_ttl_seconds=60)
    assert settings.worker_heartbeat_ttl_seconds == 60


@pytest.mark.parametrize("ttl", [0, -1, 100_000])
def test_reject_invalid_runtime_snapshot_ttl(ttl: int) -> None:
    with pytest.raises(ValidationError):
        Settings(runtime_snapshot_ttl_seconds=ttl)


@pytest.mark.parametrize("timeout", [0.0, 20.0])
def test_reject_out_of_range_probe_timeout(timeout: float) -> None:
    with pytest.raises(ValidationError):
        Settings(dependency_probe_timeout_seconds=timeout)


@pytest.mark.parametrize("limit", [0, 1000])
def test_reject_out_of_range_summary_rate_limit(limit: int) -> None:
    with pytest.raises(ValidationError):
        Settings(max_operations_summary_requests_per_minute=limit)


def test_defaults_are_sane() -> None:
    settings = Settings()
    assert settings.worker_queue_redis_key == ""  # no queue configured by default
    assert settings.worker_heartbeat_ttl_seconds >= 2 * settings.worker_heartbeat_interval_seconds
    assert settings.runtime_snapshot_ttl_seconds >= 1
