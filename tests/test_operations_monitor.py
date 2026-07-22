"""Unit tests for the bounded-collection storage service (Phase 2A).

Clock, collect, and emit are all injected, so TTL, single-flight, and the
warning throttle are exercised deterministically with no real host, Docker,
or wall-clock dependency.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from app.operations_monitor import StorageObservabilityService
from app.storage_monitor import (
    DiskThresholdStatus,
    DiskUsage,
    DockerAvailability,
    DockerStorage,
    Freshness,
    StorageSnapshot,
)

_WALL = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)


def _snapshot(used_percent: float | None) -> StorageSnapshot:
    return StorageSnapshot(
        disk=DiskUsage(
            path="/internal/secret/path",
            total_bytes=100,
            used_bytes=None if used_percent is None else int(used_percent),
            available_bytes=None,
            used_percent=used_percent,
        ),
        docker=DockerStorage(
            availability=DockerAvailability.UNAVAILABLE, reason="x", categories=()
        ),
    )


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def monotonic(self) -> float:
        return self.t

    def advance(self, d: float) -> None:
        self.t += d


class _Collector:
    def __init__(self, used_percent: float | None = 10.0) -> None:
        self.count = 0
        self.used_percent = used_percent

    def __call__(self) -> StorageSnapshot:
        self.count += 1
        return _snapshot(self.used_percent)


def _get(service, clock, collect, emit, *, ttl=30.0, cooldown=100.0):
    return service.get_snapshot(
        ttl_seconds=ttl,
        cooldown_seconds=cooldown,
        warning_percent=80.0,
        critical_percent=90.0,
        collect=collect,
        emit=emit,
        monotonic=clock.monotonic,
        now_wall=lambda: _WALL,
    )


def _noop_emit(_status, _snapshot) -> None:
    pass


# --- TTL cache + single-flight ------------------------------------------------


def test_first_call_collects_fresh() -> None:
    service = StorageObservabilityService()
    clock, collect = _Clock(), _Collector()
    result = _get(service, clock, collect, _noop_emit)
    assert result.freshness is Freshness.FRESH
    assert result.age_seconds == 0.0
    assert result.collected_at == _WALL
    assert collect.count == 1


def test_within_ttl_serves_cached_without_recollecting() -> None:
    service = StorageObservabilityService()
    clock, collect = _Clock(), _Collector()
    _get(service, clock, collect, _noop_emit)
    clock.advance(5.0)  # still < ttl (30)
    result = _get(service, clock, collect, _noop_emit)
    assert result.freshness is Freshness.CACHED
    assert result.age_seconds == 5.0
    assert collect.count == 1  # no second docker collection


def test_after_ttl_recollects() -> None:
    service = StorageObservabilityService()
    clock, collect = _Clock(), _Collector()
    _get(service, clock, collect, _noop_emit)
    clock.advance(31.0)  # > ttl
    result = _get(service, clock, collect, _noop_emit)
    assert result.freshness is Freshness.FRESH
    assert collect.count == 2


def test_repeated_rapid_calls_collect_once() -> None:
    service = StorageObservabilityService()
    clock, collect = _Clock(), _Collector()
    for _ in range(20):
        _get(service, clock, collect, _noop_emit)  # no clock advance
    assert collect.count == 1


def test_single_flight_serves_stale_when_refresh_in_progress() -> None:
    service = StorageObservabilityService()
    clock, collect = _Clock(), _Collector()
    _get(service, clock, collect, _noop_emit)  # prime cache (count=1)
    clock.advance(40.0)  # now stale (> ttl)
    # Simulate a concurrent refresher already holding the single-flight lock.
    service._refresh_lock.acquire()
    try:
        result = _get(service, clock, collect, _noop_emit)
    finally:
        service._refresh_lock.release()
    assert result.freshness is Freshness.STALE
    assert collect.count == 1  # did NOT launch a second docker subprocess


def test_reset_clears_cache() -> None:
    service = StorageObservabilityService()
    clock, collect = _Clock(), _Collector()
    _get(service, clock, collect, _noop_emit)
    service.reset()
    _get(service, clock, collect, _noop_emit)
    assert collect.count == 2


def test_single_flight_under_real_thread_concurrency() -> None:
    # 10 real threads hit a cold cache at once with a slow collector. Single-
    # flight must let exactly one collection run; the rest serve the cached
    # snapshot -- no duplicate Docker subprocesses.
    service = StorageObservabilityService()
    count_lock = threading.Lock()
    counter = {"n": 0}

    def _slow_collect() -> StorageSnapshot:
        with count_lock:
            counter["n"] += 1
        time.sleep(0.1)  # hold the refresh lock long enough for others to pile up
        return _snapshot(10.0)

    results: list[Freshness] = []
    results_lock = threading.Lock()

    def _worker() -> None:
        result = service.get_snapshot(
            ttl_seconds=30.0,
            cooldown_seconds=100.0,
            warning_percent=80.0,
            critical_percent=90.0,
            collect=_slow_collect,
            emit=_noop_emit,
            monotonic=time.monotonic,
            now_wall=lambda: _WALL,
        )
        with results_lock:
            results.append(result.freshness)

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counter["n"] == 1  # exactly one Docker collection despite 10 callers
    assert len(results) == 10
    assert results.count(Freshness.FRESH) == 1  # one collector, rest cached


# --- warning throttle ---------------------------------------------------------


class _EmitRecorder:
    def __init__(self) -> None:
        self.statuses: list[DiskThresholdStatus] = []

    def __call__(self, status: DiskThresholdStatus, _snapshot) -> None:
        self.statuses.append(status)


def test_warning_emits_once_then_deduped_within_cooldown() -> None:
    service = StorageObservabilityService()
    clock = _Clock()
    collect = _Collector(used_percent=85.0)  # warning
    emit = _EmitRecorder()
    _get(service, clock, collect, emit, ttl=1.0, cooldown=100.0)  # fresh -> emit warning
    # Force fresh recollections within the cooldown window; must NOT re-emit.
    for _ in range(5):
        clock.advance(2.0)  # > ttl(1) so it recollects, but < cooldown
        _get(service, clock, collect, emit, ttl=1.0, cooldown=100.0)
    assert emit.statuses == [DiskThresholdStatus.WARNING]


def test_warning_reemits_after_cooldown() -> None:
    service = StorageObservabilityService()
    clock = _Clock()
    collect = _Collector(used_percent=85.0)
    emit = _EmitRecorder()
    _get(service, clock, collect, emit, ttl=1.0, cooldown=100.0)
    clock.advance(150.0)  # past cooldown (and ttl) -> recollect + re-emit
    _get(service, clock, collect, emit, ttl=1.0, cooldown=100.0)
    assert emit.statuses == [DiskThresholdStatus.WARNING, DiskThresholdStatus.WARNING]


def test_escalation_warning_to_critical_emits_on_transition() -> None:
    service = StorageObservabilityService()
    clock = _Clock()
    collect = _Collector(used_percent=85.0)  # warning
    emit = _EmitRecorder()
    _get(service, clock, collect, emit, ttl=1.0, cooldown=100.0)
    collect.used_percent = 95.0  # critical
    clock.advance(2.0)  # > ttl but < cooldown; transition still emits
    _get(service, clock, collect, emit, ttl=1.0, cooldown=100.0)
    assert emit.statuses == [DiskThresholdStatus.WARNING, DiskThresholdStatus.CRITICAL]


def test_return_to_ok_then_warning_reemits_as_transition() -> None:
    service = StorageObservabilityService()
    clock = _Clock()
    collect = _Collector(used_percent=85.0)
    emit = _EmitRecorder()
    _get(service, clock, collect, emit, ttl=1.0, cooldown=100.0)  # warning -> emit
    collect.used_percent = 10.0  # back to ok
    clock.advance(2.0)
    _get(service, clock, collect, emit, ttl=1.0, cooldown=100.0)  # ok -> no emit
    collect.used_percent = 85.0  # warning again
    clock.advance(2.0)  # < cooldown, but it's a fresh transition from ok
    _get(service, clock, collect, emit, ttl=1.0, cooldown=100.0)
    assert emit.statuses == [DiskThresholdStatus.WARNING, DiskThresholdStatus.WARNING]


def test_ok_and_unknown_never_emit() -> None:
    service = StorageObservabilityService()
    clock = _Clock()
    emit = _EmitRecorder()
    _get(service, clock, _Collector(used_percent=10.0), emit, ttl=1.0)  # ok
    clock.advance(2.0)
    service.reset()
    _get(service, clock, _Collector(used_percent=None), emit, ttl=1.0)  # unknown
    assert emit.statuses == []
