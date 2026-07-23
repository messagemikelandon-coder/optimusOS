"""In-process request traffic/latency metrics (Phase 2B).

A bounded, thread-safe registry that the request-context middleware feeds one
record per completed (or failed) HTTP request. It exists so a platform-support
operator can see aggregate request volume, error rates, and latency for *this
application process* without any external metrics backend, scraping secret, or
unauthenticated ``/metrics`` endpoint.

Design constraints (all deliberate):

* **Bounded cardinality.** Requests are labelled by ``(method, route_template)``
  where ``route_template`` is FastAPI's ``route.path_format`` -- e.g.
  ``/api/customers/{customer_id}`` -- so a value like ``/api/customers/15`` never
  becomes its own label and no id, path value, or PII can enter a label. A
  request that matched no route is labelled ``<unmatched>`` (never its raw path).
  The number of distinct labels is additionally capped; once the cap is reached
  further labels fold into a single ``<other>`` bucket, so a pathological
  route explosion cannot grow this store without bound.
* **Non-sensitive by construction.** Every stored and exposed value is an
  aggregate: a count, a status-class count, or a latency total/max. There are
  no bodies, headers, query strings, usernames, ids, or raw paths.
* **Never on the hot path's critical failure surface.** ``record`` is total --
  it does arithmetic on numbers it is handed and cannot raise -- so a metrics
  update can never turn a served request into an error.

A single process-wide instance (``request_metrics``) is shared across all
requests; ``reset()`` exists only for test isolation.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

# Cap on distinct (method, route_template) labels retained. The real route table
# is far smaller than this; the cap only guards against an unforeseen explosion
# (e.g. a future catch-all route) growing the store without bound. Excess labels
# fold into a single _OVERFLOW_LABEL bucket.
_MAX_LABELS = 256
_OVERFLOW_TEMPLATE = "<other>"
_OVERFLOW_METHOD = "<other>"
UNMATCHED_TEMPLATE = "<unmatched>"

# Fixed, enumerable status classes. A status code outside 100-599 (there is no
# legitimate source of one here) folds into "other" rather than creating an
# unbounded key.
_STATUS_CLASSES = ("informational", "success", "redirect", "client_error", "server_error", "other")


def status_class(status_code: int) -> str:
    """Map an HTTP status code to a fixed, bounded severity class."""
    if 100 <= status_code < 200:
        return "informational"
    if 200 <= status_code < 300:
        return "success"
    if 300 <= status_code < 400:
        return "redirect"
    if 400 <= status_code < 500:
        return "client_error"
    if 500 <= status_code < 600:
        return "server_error"
    return "other"


@dataclass(frozen=True)
class RouteMetric:
    """Aggregate metrics for one ``(method, route_template)`` label."""

    method: str
    route: str
    count: int
    error_count: int  # 4xx + 5xx
    average_latency_ms: float
    max_latency_ms: float


@dataclass(frozen=True)
class RequestMetricsSnapshot:
    """A bounded, non-sensitive point-in-time view of process request activity."""

    uptime_seconds: float
    total_requests: int
    status_classes: dict[str, int]
    average_latency_ms: float
    max_latency_ms: float
    tracked_routes: int
    label_overflow: bool
    top_routes: list[RouteMetric]


class _Bucket:
    __slots__ = ("count", "error_count", "max_latency_ms", "sum_latency_ms")

    def __init__(self) -> None:
        self.count = 0
        self.error_count = 0
        self.sum_latency_ms = 0.0
        self.max_latency_ms = 0.0


class RequestMetricsRegistry:
    def __init__(self, *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._lock = threading.Lock()
        self._started_at = now()
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._status_classes: dict[str, int] = dict.fromkeys(_STATUS_CLASSES, 0)
        self._total = 0
        self._sum_latency_ms = 0.0
        self._max_latency_ms = 0.0
        self._overflow = False

    def reset(self) -> None:
        """Drop all counters (test-only; a real process shares one instance)."""
        with self._lock:
            self._started_at = self._now()
            self._buckets = {}
            self._status_classes = dict.fromkeys(_STATUS_CLASSES, 0)
            self._total = 0
            self._sum_latency_ms = 0.0
            self._max_latency_ms = 0.0
            self._overflow = False

    def record(
        self, *, method: str, route_template: str, status_code: int, duration_ms: float
    ) -> None:
        """Record one completed/failed request. Total by construction: it only
        does bounded arithmetic on the values handed to it, so it can never
        raise and can never turn a served request into an error."""
        cls = status_class(status_code)
        is_error = 400 <= status_code < 600
        # Clamp a nonsensical negative duration to 0 rather than letting it skew
        # the sum/max; never raises.
        latency = duration_ms if duration_ms >= 0.0 else 0.0
        method_label = method.upper() if isinstance(method, str) and method else "UNKNOWN"
        template = (
            route_template
            if isinstance(route_template, str) and route_template
            else UNMATCHED_TEMPLATE
        )
        with self._lock:
            self._total += 1
            self._status_classes[cls] = self._status_classes.get(cls, 0) + 1
            self._sum_latency_ms += latency
            if latency > self._max_latency_ms:
                self._max_latency_ms = latency

            key = (method_label, template)
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= _MAX_LABELS:
                    self._overflow = True
                    key = (_OVERFLOW_METHOD, _OVERFLOW_TEMPLATE)
                    bucket = self._buckets.get(key)
                    if bucket is None:
                        bucket = _Bucket()
                        self._buckets[key] = bucket
                else:
                    bucket = _Bucket()
                    self._buckets[key] = bucket
            bucket.count += 1
            if is_error:
                bucket.error_count += 1
            bucket.sum_latency_ms += latency
            if latency > bucket.max_latency_ms:
                bucket.max_latency_ms = latency

    def snapshot(self, *, top_n: int = 10) -> RequestMetricsSnapshot:
        """Return a bounded, non-sensitive view. ``top_n`` caps how many
        per-route entries are included (highest request count first)."""
        with self._lock:
            uptime = max(0.0, self._now() - self._started_at)
            total = self._total
            avg = (self._sum_latency_ms / total) if total else 0.0
            status_classes = dict(self._status_classes)
            max_latency = self._max_latency_ms
            tracked = len(self._buckets)
            overflow = self._overflow
            items = [
                RouteMetric(
                    method=method,
                    route=template,
                    count=bucket.count,
                    error_count=bucket.error_count,
                    average_latency_ms=round(bucket.sum_latency_ms / bucket.count, 3)
                    if bucket.count
                    else 0.0,
                    max_latency_ms=round(bucket.max_latency_ms, 3),
                )
                for (method, template), bucket in self._buckets.items()
            ]
        # Deterministic ordering: most requests first, then method/route for ties.
        items.sort(key=lambda m: (-m.count, m.method, m.route))
        limit = top_n if top_n >= 0 else 0
        return RequestMetricsSnapshot(
            uptime_seconds=round(uptime, 3),
            total_requests=total,
            status_classes=status_classes,
            average_latency_ms=round(avg, 3),
            max_latency_ms=round(max_latency, 3),
            tracked_routes=tracked,
            label_overflow=overflow,
            top_routes=items[:limit],
        )


# Process-wide instance shared across every request. Tests call reset() for
# isolation; a real process never does.
request_metrics = RequestMetricsRegistry()
