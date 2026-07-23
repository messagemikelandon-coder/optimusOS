"""Bounded collection + warning throttling for storage observability (Phase 2A).

Wraps the stateless collector in ``app/storage_monitor.py`` so the read-only
support endpoint reads a *bounded* snapshot instead of launching an unbounded
Docker subprocess on every request:

- **TTL cache** — a collected snapshot is reused for a configurable time-to-live.
- **Single-flight** — concurrent requests never launch duplicate Docker
  subprocesses: exactly one refresher runs per TTL window; others serve the
  last snapshot (labelled ``cached``/``stale``) or, only if none exists yet,
  wait for the in-flight refresh.
- **Warning throttle** — a reliability warning is emitted only on a
  fresh collection, and then only on a severity transition or after a
  configurable cooldown, so repeated requests during the same
  warning/critical state do not amplify into repeated log events.

Pure state lives on a single process-wide instance (``storage_service``);
``reset()`` exists for test isolation. All time is injected (``monotonic`` /
``now_wall``) so tests drive TTL/cooldown deterministically, and the collect
and emit callables are injected so nothing here touches a real host, Docker
daemon, or the logging config directly.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.storage_monitor import (
    DiskThresholdStatus,
    Freshness,
    StorageSnapshot,
    classify_disk_status,
)


@dataclass(frozen=True)
class BoundedSnapshot:
    snapshot: StorageSnapshot
    freshness: Freshness
    collected_at: datetime
    age_seconds: float


# Signature of the warning-emit callable the caller supplies (it owns the
# logger and the request's support-actor identity). Called at most once per
# fresh collection that crosses a threshold, subject to the throttle.
EmitWarning = Callable[[DiskThresholdStatus, StorageSnapshot], None]


class StorageObservabilityService:
    def __init__(self) -> None:
        # Guards the cached snapshot references (fast, never held across a
        # collection). Distinct from the single-flight refresh lock.
        self._state_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._snapshot: StorageSnapshot | None = None
        self._collected_at_monotonic: float | None = None
        self._collected_at_wall: datetime | None = None
        # Warning-throttle state. Only ever written by the single-flight
        # refresh-lock holder (in _maybe_emit, reached only from the fresh-
        # collect path), so no additional lock is needed at runtime; reset()
        # clears it under _state_lock for test isolation only.
        self._last_emitted_status: DiskThresholdStatus | None = None
        self._last_emit_monotonic: float | None = None

    def reset(self) -> None:
        """Drop all cache and throttle state. Test-only; a real process shares
        one instance across every request."""
        with self._state_lock:
            self._snapshot = None
            self._collected_at_monotonic = None
            self._collected_at_wall = None
            self._last_emitted_status = None
            self._last_emit_monotonic = None

    def peek_snapshot(self, *, monotonic: Callable[[], float]) -> BoundedSnapshot | None:
        """Return the currently-cached snapshot WITHOUT ever collecting. Used by
        the Phase 2B operational summary to reuse the Phase 2A storage snapshot:
        it must never launch a Docker subprocess of its own, so it reads only
        what the dedicated ``/api/operations/storage`` endpoint has already
        collected. Returns ``None`` when nothing has been collected yet. This
        labels an existing snapshot ``CACHED`` and reports its age; the caller
        supplies no TTL, so any staleness judgment is left to the caller."""
        now = monotonic()
        with self._state_lock:
            snapshot = self._snapshot
            collected_mono = self._collected_at_monotonic
            collected_wall = self._collected_at_wall
        if snapshot is None or collected_mono is None or collected_wall is None:
            return None
        return BoundedSnapshot(snapshot, Freshness.CACHED, collected_wall, now - collected_mono)

    def get_snapshot(
        self,
        *,
        ttl_seconds: float,
        cooldown_seconds: float,
        warning_percent: float,
        critical_percent: float,
        collect: Callable[[], StorageSnapshot],
        emit: EmitWarning,
        monotonic: Callable[[], float],
        now_wall: Callable[[], datetime],
    ) -> BoundedSnapshot:
        now = monotonic()

        with self._state_lock:
            snapshot = self._snapshot
            collected_mono = self._collected_at_monotonic
            collected_wall = self._collected_at_wall

        # Fast path: a still-fresh cache serves without touching the refresh
        # lock or launching any subprocess.
        if (
            snapshot is not None
            and collected_mono is not None
            and collected_wall is not None
            and (now - collected_mono) < ttl_seconds
        ):
            return BoundedSnapshot(snapshot, Freshness.CACHED, collected_wall, now - collected_mono)

        # Refresh needed. Single-flight: only the lock holder collects. If a
        # prior snapshot exists we never block -- a concurrent refresher is
        # already running, so we serve the last snapshot (cached/stale) rather
        # than launching a second Docker subprocess.
        block = snapshot is None
        acquired = self._refresh_lock.acquire(blocking=block)
        if not acquired:
            assert snapshot is not None and collected_mono is not None
            age = now - collected_mono
            freshness = Freshness.CACHED if age < ttl_seconds else Freshness.STALE
            return BoundedSnapshot(snapshot, freshness, collected_wall or now_wall(), age)

        try:
            # Re-check under the refresh lock: another thread may have just
            # refreshed while we waited for the lock.
            now2 = monotonic()
            with self._state_lock:
                snapshot2 = self._snapshot
                collected_mono2 = self._collected_at_monotonic
                collected_wall2 = self._collected_at_wall
            if (
                snapshot2 is not None
                and collected_mono2 is not None
                and collected_wall2 is not None
                and (now2 - collected_mono2) < ttl_seconds
            ):
                return BoundedSnapshot(
                    snapshot2, Freshness.CACHED, collected_wall2, now2 - collected_mono2
                )

            fresh = collect()  # the single Docker subprocess for this TTL window
            wall = now_wall()
            mono = monotonic()
            with self._state_lock:
                self._snapshot = fresh
                self._collected_at_monotonic = mono
                self._collected_at_wall = wall
            self._maybe_emit(
                fresh,
                warning_percent=warning_percent,
                critical_percent=critical_percent,
                cooldown_seconds=cooldown_seconds,
                emit=emit,
                mono=mono,
            )
            return BoundedSnapshot(fresh, Freshness.FRESH, wall, 0.0)
        finally:
            self._refresh_lock.release()

    def _maybe_emit(
        self,
        snapshot: StorageSnapshot,
        *,
        warning_percent: float,
        critical_percent: float,
        cooldown_seconds: float,
        emit: EmitWarning,
        mono: float,
    ) -> None:
        """Emit a reliability warning only on a severity transition into (or
        between) warning/critical, or after the cooldown has elapsed while the
        elevated state persists. Called only from a fresh collection, so cached
        and stale serves never emit."""
        status = classify_disk_status(
            snapshot.disk.used_percent,
            warning_percent=warning_percent,
            critical_percent=critical_percent,
        )
        if status in (DiskThresholdStatus.WARNING, DiskThresholdStatus.CRITICAL):
            transitioned = status != self._last_emitted_status
            cooled = (
                self._last_emit_monotonic is None
                or (mono - self._last_emit_monotonic) >= cooldown_seconds
            )
            if transitioned or cooled:
                emit(status, snapshot)
                self._last_emit_monotonic = mono
            self._last_emitted_status = status
        else:
            # Returning to ok/unknown clears the elevated state, so a later
            # warning/critical counts as a fresh transition and emits again.
            self._last_emitted_status = status


# Process-wide instance shared across requests. Tests call reset() for
# isolation; a real process never does.
storage_service = StorageObservabilityService()
