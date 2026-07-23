"""Bounded runtime observability collection (Phase 2B).

Collects three cheap, read-only runtime signals for the support operational
summary and wraps them in the same bounded-collection discipline Phase 2A uses
for storage (``app/operations_monitor.py``): a TTL cache + non-blocking
single-flight refresh + a throttled reliability warning, so repeated summary
requests never amplify into repeated dependency probes or repeated log events.

The three signals -- all fail-safe, none ever raising for a real dependency
failure, none ever carrying customer/tenant/secret data:

* **Dependency status** -- Postgres and Redis TCP reachability, via the same
  fail-safe probe ``/ready`` uses (``app/net.py``). Reported as a fixed
  ``reachable``/``unreachable`` enum, never a URL or error string.
* **Worker heartbeat** -- a single fixed Redis key the background worker
  refreshes with a bounded TTL (see ``scripts/optimus_worker.py``). Read only;
  the value is an epoch second used to compute the heartbeat's age. Reported as
  ``alive``/``stale``/``missing``/``unknown`` -- never a pid, host, or payload.
* **Queue condition** -- OPT-IN and OFF BY DEFAULT. There is no application work
  queue in this codebase today (ADR-014 records that any future queue would be a
  Postgres ``SKIP LOCKED`` queue, not Redis), so with no key configured this
  reports ``not_configured`` and never touches Redis for the queue at all. If an
  operator later points a config key at a real Redis list, it is read with a
  single bounded ``LLEN`` and reported as ``idle``/``backlog``/``unknown`` --
  depth only, never a queued item.

All host/Redis boundaries are injected so unit tests never touch a real daemon.
A single process-wide instance (``runtime_service``) is shared; ``reset()``
exists only for test isolation.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

from redis import Redis
from redis.exceptions import ResponseError

from app.net import _tcp_dependency_ready
from app.storage_monitor import Freshness


class DependencyStatus(StrEnum):
    REACHABLE = "reachable"
    # The TCP probe could not connect (daemon down, wrong host/port, network
    # error). Fail-safe: never asserted as reachable on an error.
    UNREACHABLE = "unreachable"


class WorkerHeartbeatStatus(StrEnum):
    """Liveness of the background worker, inferred from its Redis heartbeat key."""

    ALIVE = "alive"  # key present and fresher than its TTL window
    STALE = "stale"  # key present but older than its TTL window (clock skew)
    MISSING = "missing"  # key absent -- worker down, never started, or expired
    UNKNOWN = "unknown"  # Redis unreachable or the value was unparseable


class QueueStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"  # no queue key configured (the default)
    IDLE = "idle"  # configured key present, depth 0
    BACKLOG = "backlog"  # configured key present, depth > 0
    UNKNOWN = "unknown"  # Redis unreachable, wrong type, or unreadable


@dataclass(frozen=True)
class DependencySnapshot:
    postgres: DependencyStatus
    redis: DependencyStatus


@dataclass(frozen=True)
class WorkerHeartbeatSnapshot:
    status: WorkerHeartbeatStatus
    age_seconds: float | None  # None unless status is ALIVE/STALE
    ttl_seconds: int


@dataclass(frozen=True)
class QueueSnapshot:
    status: QueueStatus
    depth: int | None  # None unless status is IDLE/BACKLOG


@dataclass(frozen=True)
class RuntimeSignals:
    dependencies: DependencySnapshot
    worker: WorkerHeartbeatSnapshot
    queue: QueueSnapshot


@dataclass(frozen=True)
class BoundedRuntimeSnapshot:
    signals: RuntimeSignals
    freshness: Freshness
    collected_at: datetime
    age_seconds: float


@dataclass(frozen=True)
class _RedisReadout:
    """Raw, already-sanitized result of the single Redis read pass. Carries no
    URL, error text, or payload -- only reachability, the heartbeat's raw epoch
    string (if any), and the queue depth (if a queue key was queried)."""

    reachable: bool
    heartbeat_raw: str | None
    queue_depth: int | None
    queue_errored: bool


# Severity a fresh runtime snapshot rolls up to, for the throttled warning.
RUNTIME_SEVERITY_OK = "ok"
RUNTIME_SEVERITY_DEGRADED = "degraded"

# Signature of the caller-supplied warning emitter (owns the logger and the
# support-actor identity). Called at most once per fresh collection that is
# degraded, subject to the throttle.
EmitRuntimeWarning = Callable[[str, RuntimeSignals], None]


def runtime_severity(signals: RuntimeSignals) -> str:
    """Roll a snapshot up to ok/degraded for the reliability-warning throttle.
    Degraded when a core dependency is unreachable or the worker is not alive.
    A ``not_configured`` queue is not degradation (it is the expected default);
    a ``unknown`` queue is not counted either, to avoid false alarms when only
    Redis reads for the optional queue fail."""
    if (
        signals.dependencies.postgres is DependencyStatus.UNREACHABLE
        or signals.dependencies.redis is DependencyStatus.UNREACHABLE
        or signals.worker.status in (WorkerHeartbeatStatus.MISSING, WorkerHeartbeatStatus.STALE)
    ):
        return RUNTIME_SEVERITY_DEGRADED
    return RUNTIME_SEVERITY_OK


def _default_redis_reader(
    redis_url: str, heartbeat_key: str, queue_key: str, timeout_seconds: float
) -> _RedisReadout:
    """Real Redis read boundary: one GET (heartbeat) and, only if a queue key is
    configured, one LLEN (queue depth). Fail-safe -- ANY error (a connection or
    timeout ``RedisError``/``OSError``, or an unexpected error such as a
    ``ValueError`` from ``Redis.from_url`` on a malformed URL) yields an
    unreachable readout rather than propagating, so a bad Redis config degrades
    only this one subsection of the summary and never 500s the endpoint. Never
    leaks the URL or error text. Injected in tests so no real Redis is touched."""
    client: Redis | None = None
    try:
        client = Redis.from_url(
            redis_url,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )
        # The synchronous redis-py client's type stubs union the sync and async
        # return types (``Awaitable[T] | T``); this is the sync client, so the
        # concrete result is the non-awaitable branch. cast() records that fact
        # for the type checker without changing runtime behavior.
        raw = cast("bytes | str | None", client.get(heartbeat_key))
        heartbeat_raw: str | None
        if raw is None:
            heartbeat_raw = None
        elif isinstance(raw, bytes):
            heartbeat_raw = raw.decode("utf-8", "replace")
        else:
            heartbeat_raw = str(raw)

        queue_depth: int | None = None
        queue_errored = False
        if queue_key:
            try:
                queue_depth = int(cast("int", client.llen(queue_key)))
            except (ResponseError, ValueError, TypeError):
                # Wrong Redis type at the key, or a non-integer reply -- report
                # the queue as unknown rather than failing the whole readout.
                queue_errored = True
        return _RedisReadout(
            reachable=True,
            heartbeat_raw=heartbeat_raw,
            queue_depth=queue_depth,
            queue_errored=queue_errored,
        )
    except Exception:
        # Last-resort fail-safe boundary (not defect-hiding): this reader is the
        # summary's one Redis touchpoint and MUST NOT propagate. Expected errors
        # are connection/timeout (RedisError/OSError); a malformed redis_url can
        # also raise ValueError at from_url. Either way the runtime signals
        # degrade to "unknown", never a 500 that loses the request/capability/
        # storage sections that have nothing to do with Redis.
        return _RedisReadout(
            reachable=False, heartbeat_raw=None, queue_depth=None, queue_errored=False
        )
    finally:
        if client is not None:
            # Best-effort cleanup of a read-only client; never mask the readout
            # we already computed.
            with contextlib.suppress(Exception):
                client.close()


def collect_runtime_signals(
    *,
    database_url: str,
    redis_url: str,
    probe_timeout_seconds: float,
    heartbeat_key: str,
    heartbeat_ttl_seconds: int,
    queue_key: str,
    now_epoch: Callable[[], float],
    tcp_probe: Callable[[str, int, float], bool] = _tcp_dependency_ready,
    redis_reader: Callable[[str, str, str, float], _RedisReadout] = _default_redis_reader,
) -> RuntimeSignals:
    """Collect all three runtime signals once. Never raises for a real
    dependency failure: each probe/read degrades to an unreachable/unknown
    fixed status. This is the only place the dependency probes and the Redis
    read run; the caller's cache/single-flight layer bounds how often."""
    postgres_ready = tcp_probe(database_url, 5432, probe_timeout_seconds)
    redis_ready = tcp_probe(redis_url, 6379, probe_timeout_seconds)
    dependencies = DependencySnapshot(
        postgres=DependencyStatus.REACHABLE if postgres_ready else DependencyStatus.UNREACHABLE,
        redis=DependencyStatus.REACHABLE if redis_ready else DependencyStatus.UNREACHABLE,
    )

    readout = redis_reader(redis_url, heartbeat_key, queue_key, probe_timeout_seconds)
    worker = _interpret_heartbeat(
        readout, heartbeat_ttl_seconds=heartbeat_ttl_seconds, now_epoch=now_epoch
    )
    queue = _interpret_queue(readout, queue_key=queue_key)
    return RuntimeSignals(dependencies=dependencies, worker=worker, queue=queue)


def _interpret_heartbeat(
    readout: _RedisReadout, *, heartbeat_ttl_seconds: int, now_epoch: Callable[[], float]
) -> WorkerHeartbeatSnapshot:
    if not readout.reachable:
        return WorkerHeartbeatSnapshot(
            status=WorkerHeartbeatStatus.UNKNOWN,
            age_seconds=None,
            ttl_seconds=heartbeat_ttl_seconds,
        )
    if readout.heartbeat_raw is None:
        return WorkerHeartbeatSnapshot(
            status=WorkerHeartbeatStatus.MISSING,
            age_seconds=None,
            ttl_seconds=heartbeat_ttl_seconds,
        )
    try:
        beat_epoch = float(readout.heartbeat_raw)
    except (ValueError, OverflowError):
        return WorkerHeartbeatSnapshot(
            status=WorkerHeartbeatStatus.UNKNOWN,
            age_seconds=None,
            ttl_seconds=heartbeat_ttl_seconds,
        )
    if beat_epoch != beat_epoch or beat_epoch in (float("inf"), float("-inf")):  # NaN/inf guard
        return WorkerHeartbeatSnapshot(
            status=WorkerHeartbeatStatus.UNKNOWN,
            age_seconds=None,
            ttl_seconds=heartbeat_ttl_seconds,
        )
    age = now_epoch() - beat_epoch
    if age < 0.0:
        age = 0.0  # clock skew: a future timestamp is treated as just-beaten
    status = (
        WorkerHeartbeatStatus.ALIVE if age <= heartbeat_ttl_seconds else WorkerHeartbeatStatus.STALE
    )
    return WorkerHeartbeatSnapshot(
        status=status, age_seconds=round(age, 3), ttl_seconds=heartbeat_ttl_seconds
    )


def _interpret_queue(readout: _RedisReadout, *, queue_key: str) -> QueueSnapshot:
    if not queue_key:
        return QueueSnapshot(status=QueueStatus.NOT_CONFIGURED, depth=None)
    if not readout.reachable or readout.queue_errored or readout.queue_depth is None:
        return QueueSnapshot(status=QueueStatus.UNKNOWN, depth=None)
    depth = readout.queue_depth
    if depth < 0:
        return QueueSnapshot(status=QueueStatus.UNKNOWN, depth=None)
    return QueueSnapshot(
        status=QueueStatus.IDLE if depth == 0 else QueueStatus.BACKLOG, depth=depth
    )


class RuntimeObservabilityService:
    """TTL-cached, single-flight wrapper around ``collect_runtime_signals`` with
    a throttled degraded-warning, mirroring ``StorageObservabilityService``. At
    most one probe/read pass runs per TTL window; concurrent requests serve the
    last snapshot rather than launching a second pass."""

    def __init__(self) -> None:
        self._state_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._signals: RuntimeSignals | None = None
        self._collected_at_monotonic: float | None = None
        self._collected_at_wall: datetime | None = None
        # Warning-throttle state, written only by the single-flight refresh
        # holder (in _maybe_emit, reached only from the fresh-collect path).
        self._last_emitted_severity: str | None = None
        self._last_emit_monotonic: float | None = None

    def reset(self) -> None:
        with self._state_lock:
            self._signals = None
            self._collected_at_monotonic = None
            self._collected_at_wall = None
            self._last_emitted_severity = None
            self._last_emit_monotonic = None

    def get_snapshot(
        self,
        *,
        ttl_seconds: float,
        cooldown_seconds: float,
        collect: Callable[[], RuntimeSignals],
        emit: EmitRuntimeWarning,
        monotonic: Callable[[], float],
        now_wall: Callable[[], datetime],
    ) -> BoundedRuntimeSnapshot:
        now = monotonic()

        with self._state_lock:
            signals = self._signals
            collected_mono = self._collected_at_monotonic
            collected_wall = self._collected_at_wall

        if (
            signals is not None
            and collected_mono is not None
            and collected_wall is not None
            and (now - collected_mono) < ttl_seconds
        ):
            return BoundedRuntimeSnapshot(
                signals, Freshness.CACHED, collected_wall, now - collected_mono
            )

        block = signals is None
        acquired = self._refresh_lock.acquire(blocking=block)
        if not acquired:
            assert signals is not None and collected_mono is not None
            age = now - collected_mono
            freshness = Freshness.CACHED if age < ttl_seconds else Freshness.STALE
            return BoundedRuntimeSnapshot(signals, freshness, collected_wall or now_wall(), age)

        try:
            now2 = monotonic()
            with self._state_lock:
                signals2 = self._signals
                collected_mono2 = self._collected_at_monotonic
                collected_wall2 = self._collected_at_wall
            if (
                signals2 is not None
                and collected_mono2 is not None
                and collected_wall2 is not None
                and (now2 - collected_mono2) < ttl_seconds
            ):
                return BoundedRuntimeSnapshot(
                    signals2, Freshness.CACHED, collected_wall2, now2 - collected_mono2
                )

            fresh = collect()
            wall = now_wall()
            mono = monotonic()
            with self._state_lock:
                self._signals = fresh
                self._collected_at_monotonic = mono
                self._collected_at_wall = wall
            self._maybe_emit(fresh, cooldown_seconds=cooldown_seconds, emit=emit, mono=mono)
            return BoundedRuntimeSnapshot(fresh, Freshness.FRESH, wall, 0.0)
        finally:
            self._refresh_lock.release()

    def _maybe_emit(
        self,
        signals: RuntimeSignals,
        *,
        cooldown_seconds: float,
        emit: EmitRuntimeWarning,
        mono: float,
    ) -> None:
        """Emit a degraded reliability warning only on a transition into
        degraded or after the cooldown while it persists. Only ever called from
        a fresh collection, so cached/stale serves never emit."""
        severity = runtime_severity(signals)
        if severity == RUNTIME_SEVERITY_DEGRADED:
            transitioned = severity != self._last_emitted_severity
            cooled = (
                self._last_emit_monotonic is None
                or (mono - self._last_emit_monotonic) >= cooldown_seconds
            )
            if transitioned or cooled:
                emit(severity, signals)
                self._last_emit_monotonic = mono
            self._last_emitted_severity = severity
        else:
            self._last_emitted_severity = severity


# Process-wide instance shared across requests. Tests call reset() for
# isolation; a real process never does.
runtime_service = RuntimeObservabilityService()
