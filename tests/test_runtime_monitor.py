"""Unit tests for Phase 2B bounded runtime observability.

Two layers:
* ``collect_runtime_signals`` + the interpret helpers, with the TCP probe and
  Redis read boundaries injected, so dependency/heartbeat/queue interpretation
  is exercised without a real Postgres/Redis. Every failure path is asserted to
  degrade to a fixed status rather than raise.
* ``RuntimeObservabilityService`` TTL cache, single-flight, reset, and the
  throttled degraded warning, with clock/collect/emit injected.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from app.runtime_monitor import (
    RUNTIME_SEVERITY_DEGRADED,
    DependencyStatus,
    QueueStatus,
    RuntimeObservabilityService,
    RuntimeSignals,
    WorkerHeartbeatStatus,
    _default_redis_reader,
    _RedisReadout,
    collect_runtime_signals,
    runtime_severity,
)
from app.storage_monitor import Freshness

_WALL = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


def _reader(*, reachable=True, heartbeat_raw=None, queue_depth=None, queue_errored=False):
    def _r(_url: str, _hb: str, _q: str, _timeout: float) -> _RedisReadout:
        return _RedisReadout(
            reachable=reachable,
            heartbeat_raw=heartbeat_raw,
            queue_depth=queue_depth,
            queue_errored=queue_errored,
        )

    return _r


def _collect(
    *,
    postgres=True,
    redis=True,
    reader=None,
    queue_key="",
    now=1000.0,
    heartbeat_ttl=150,
) -> RuntimeSignals:
    def _probe(url: str, port: int, timeout: float) -> bool:
        return postgres if port == 5432 else redis

    return collect_runtime_signals(
        database_url="postgresql://db:5432/x",
        redis_url="redis://r:6379/0",
        probe_timeout_seconds=1.0,
        heartbeat_key="hb",
        heartbeat_ttl_seconds=heartbeat_ttl,
        queue_key=queue_key,
        now_epoch=lambda: now,
        tcp_probe=_probe,
        redis_reader=reader or _reader(),
    )


# --- dependency status --------------------------------------------------------


def test_dependencies_reachable_and_unreachable() -> None:
    up = _collect(postgres=True, redis=True)
    assert up.dependencies.postgres is DependencyStatus.REACHABLE
    assert up.dependencies.redis is DependencyStatus.REACHABLE
    down = _collect(postgres=False, redis=False)
    assert down.dependencies.postgres is DependencyStatus.UNREACHABLE
    assert down.dependencies.redis is DependencyStatus.UNREACHABLE


# --- worker heartbeat ---------------------------------------------------------


def test_heartbeat_alive_when_fresh() -> None:
    signals = _collect(reader=_reader(heartbeat_raw="990.0"), now=1000.0, heartbeat_ttl=150)
    assert signals.worker.status is WorkerHeartbeatStatus.ALIVE
    assert signals.worker.age_seconds == 10.0
    assert signals.worker.ttl_seconds == 150


def test_heartbeat_stale_when_older_than_ttl() -> None:
    signals = _collect(reader=_reader(heartbeat_raw="800.0"), now=1000.0, heartbeat_ttl=150)
    assert signals.worker.status is WorkerHeartbeatStatus.STALE
    assert signals.worker.age_seconds == 200.0


def test_heartbeat_missing_when_key_absent() -> None:
    signals = _collect(reader=_reader(heartbeat_raw=None))
    assert signals.worker.status is WorkerHeartbeatStatus.MISSING
    assert signals.worker.age_seconds is None


def test_heartbeat_unknown_when_redis_unreachable() -> None:
    signals = _collect(reader=_reader(reachable=False))
    assert signals.worker.status is WorkerHeartbeatStatus.UNKNOWN
    assert signals.worker.age_seconds is None


def test_heartbeat_unknown_when_value_malformed() -> None:
    signals = _collect(reader=_reader(heartbeat_raw="not-a-number"))
    assert signals.worker.status is WorkerHeartbeatStatus.UNKNOWN


def test_heartbeat_future_timestamp_clamped_to_alive() -> None:
    # Clock skew: a heartbeat timestamp in the future must not read as negative
    # age or stale; it clamps to age 0 and alive.
    signals = _collect(reader=_reader(heartbeat_raw="1010.0"), now=1000.0)
    assert signals.worker.status is WorkerHeartbeatStatus.ALIVE
    assert signals.worker.age_seconds == 0.0


def test_heartbeat_infinite_value_is_unknown() -> None:
    signals = _collect(reader=_reader(heartbeat_raw="inf"))
    assert signals.worker.status is WorkerHeartbeatStatus.UNKNOWN


# --- queue condition ----------------------------------------------------------


def test_queue_not_configured_by_default() -> None:
    signals = _collect(queue_key="")
    assert signals.queue.status is QueueStatus.NOT_CONFIGURED
    assert signals.queue.depth is None


def test_queue_idle_when_depth_zero() -> None:
    signals = _collect(queue_key="q", reader=_reader(queue_depth=0))
    assert signals.queue.status is QueueStatus.IDLE
    assert signals.queue.depth == 0


def test_queue_backlog_when_depth_positive() -> None:
    signals = _collect(queue_key="q", reader=_reader(queue_depth=7))
    assert signals.queue.status is QueueStatus.BACKLOG
    assert signals.queue.depth == 7


def test_queue_unknown_when_redis_unreachable() -> None:
    signals = _collect(queue_key="q", reader=_reader(reachable=False))
    assert signals.queue.status is QueueStatus.UNKNOWN
    assert signals.queue.depth is None


def test_queue_unknown_when_wrong_type() -> None:
    signals = _collect(queue_key="q", reader=_reader(queue_errored=True))
    assert signals.queue.status is QueueStatus.UNKNOWN


def test_queue_unknown_when_depth_negative() -> None:
    signals = _collect(queue_key="q", reader=_reader(queue_depth=-1))
    assert signals.queue.status is QueueStatus.UNKNOWN


# --- severity -----------------------------------------------------------------


def test_severity_degraded_on_dependency_down() -> None:
    assert runtime_severity(_collect(postgres=False)) == RUNTIME_SEVERITY_DEGRADED
    assert runtime_severity(_collect(redis=False)) == RUNTIME_SEVERITY_DEGRADED


def test_severity_degraded_on_worker_not_alive() -> None:
    assert (
        runtime_severity(_collect(reader=_reader(heartbeat_raw=None))) == RUNTIME_SEVERITY_DEGRADED
    )


def test_severity_ok_when_all_healthy_and_queue_not_configured() -> None:
    healthy = _collect(reader=_reader(heartbeat_raw="1000.0"), now=1000.0)
    assert runtime_severity(healthy) == "ok"


def test_severity_ok_when_only_optional_queue_unknown() -> None:
    # A failing optional-queue read must not by itself flip the process to
    # degraded (avoids false alarms).
    signals = _collect(
        queue_key="q", reader=_reader(heartbeat_raw="1000.0", queue_errored=True), now=1000.0
    )
    assert runtime_severity(signals) == "ok"


# --- default redis reader is fail-safe ----------------------------------------


def test_default_redis_reader_unreachable_is_failsafe() -> None:
    # Points at a closed port; must degrade to an unreachable readout, never
    # raise, and never expose the URL.
    readout = _default_redis_reader("redis://127.0.0.1:1/0", "hb", "", 0.1)
    assert readout.reachable is False
    assert readout.heartbeat_raw is None
    assert readout.queue_depth is None


def test_default_redis_reader_malformed_url_is_failsafe() -> None:
    # A malformed URL that makes Redis.from_url raise (e.g. ValueError) must
    # still degrade to an unreachable readout, never propagate and 500 the
    # summary's other (unrelated) subsections.
    readout = _default_redis_reader("not-a-valid-redis-url", "hb", "q", 0.1)
    assert readout.reachable is False
    assert readout.heartbeat_raw is None
    assert readout.queue_depth is None


# --- bounded service: TTL / single-flight / reset -----------------------------


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def monotonic(self) -> float:
        return self.t

    def advance(self, d: float) -> None:
        self.t += d


class _Collector:
    def __init__(self, signals: RuntimeSignals) -> None:
        self.count = 0
        self._signals = signals

    def __call__(self) -> RuntimeSignals:
        self.count += 1
        return self._signals


def _healthy() -> RuntimeSignals:
    return _collect(reader=_reader(heartbeat_raw="1000.0"), now=1000.0)


def _degraded() -> RuntimeSignals:
    return _collect(postgres=False)


def _get(service, clock, collect, emit, *, ttl=15.0, cooldown=300.0):
    return service.get_snapshot(
        ttl_seconds=ttl,
        cooldown_seconds=cooldown,
        collect=collect,
        emit=emit,
        monotonic=clock.monotonic,
        now_wall=lambda: _WALL,
    )


def _noop_emit(_severity, _signals) -> None:
    pass


def test_first_call_collects_fresh_then_cached_within_ttl() -> None:
    service = RuntimeObservabilityService()
    clock, collect = _Clock(), _Collector(_healthy())
    first = _get(service, clock, collect, _noop_emit)
    assert first.freshness is Freshness.FRESH
    clock.advance(5.0)
    second = _get(service, clock, collect, _noop_emit)
    assert second.freshness is Freshness.CACHED
    assert collect.count == 1


def test_recollects_after_ttl() -> None:
    service = RuntimeObservabilityService()
    clock, collect = _Clock(), _Collector(_healthy())
    _get(service, clock, collect, _noop_emit)
    clock.advance(20.0)
    third = _get(service, clock, collect, _noop_emit)
    assert third.freshness is Freshness.FRESH
    assert collect.count == 2


def test_reset_clears_cache() -> None:
    service = RuntimeObservabilityService()
    clock, collect = _Clock(), _Collector(_healthy())
    _get(service, clock, collect, _noop_emit)
    service.reset()
    again = _get(service, clock, collect, _noop_emit)
    assert again.freshness is Freshness.FRESH
    assert collect.count == 2


def test_single_flight_serves_stale_without_second_collection() -> None:
    service = RuntimeObservabilityService()
    clock = _Clock()
    started = threading.Event()
    release = threading.Event()

    def _slow_collect() -> RuntimeSignals:
        started.set()
        release.wait(2.0)
        return _healthy()

    # Prime a snapshot so a concurrent refresh has something to serve.
    _get(service, clock, _Collector(_healthy()), _noop_emit)
    clock.advance(100.0)  # force the cache stale

    holder = threading.Thread(target=lambda: _get(service, clock, _slow_collect, _noop_emit))
    holder.start()
    assert started.wait(2.0)
    # While the refresh holds the lock, a second caller must not block on a
    # second collection -- it serves the last snapshot, labelled stale.
    result = _get(service, clock, _Collector(_healthy()), _noop_emit)
    assert result.freshness is Freshness.STALE
    release.set()
    holder.join(2.0)


# --- bounded service: throttled degraded warning ------------------------------


def test_degraded_emits_once_then_dedupes_within_cooldown() -> None:
    service = RuntimeObservabilityService()
    clock = _Clock()
    emitted: list[str] = []

    def _emit(severity, _signals) -> None:
        emitted.append(severity)

    _get(service, clock, _Collector(_degraded()), _emit)
    clock.advance(20.0)  # past TTL, fresh collect, still degraded, within cooldown
    _get(service, clock, _Collector(_degraded()), _emit)
    assert emitted == [RUNTIME_SEVERITY_DEGRADED]


def test_degraded_reemits_after_cooldown() -> None:
    service = RuntimeObservabilityService()
    clock = _Clock()
    emitted: list[str] = []

    def _emit(severity, _signals) -> None:
        emitted.append(severity)

    _get(service, clock, _Collector(_degraded()), _emit, cooldown=100.0)
    clock.advance(150.0)  # past TTL and past cooldown
    _get(service, clock, _Collector(_degraded()), _emit, cooldown=100.0)
    assert emitted == [RUNTIME_SEVERITY_DEGRADED, RUNTIME_SEVERITY_DEGRADED]


def test_ok_never_emits() -> None:
    service = RuntimeObservabilityService()
    clock = _Clock()
    emitted: list[str] = []
    _get(service, clock, _Collector(_healthy()), lambda s, _: emitted.append(s))
    assert emitted == []


def test_recovery_then_degraded_reemits_as_transition() -> None:
    service = RuntimeObservabilityService()
    clock = _Clock()
    emitted: list[str] = []

    def _emit(severity, _signals) -> None:
        emitted.append(severity)

    _get(service, clock, _Collector(_degraded()), _emit, cooldown=10_000.0)
    clock.advance(20.0)
    _get(service, clock, _Collector(_healthy()), _emit, cooldown=10_000.0)  # recovers
    clock.advance(20.0)
    _get(service, clock, _Collector(_degraded()), _emit, cooldown=10_000.0)  # degrades again
    # Even well within cooldown, the ok in the middle makes the second degraded a
    # fresh transition that re-emits.
    assert emitted == [RUNTIME_SEVERITY_DEGRADED, RUNTIME_SEVERITY_DEGRADED]


def test_concurrent_get_collects_once_under_contention() -> None:
    service = RuntimeObservabilityService()
    clock = _Clock()
    collect = _Collector(_healthy())
    barrier = threading.Barrier(10)

    def _worker() -> None:
        barrier.wait()
        _get(service, clock, collect, _noop_emit)

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # First-ever collection has no prior snapshot to serve, so contenders wait
    # on the single-flight lock rather than launching duplicate collections.
    assert collect.count == 1
