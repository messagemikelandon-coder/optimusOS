"""Unit tests for the Phase 2B in-process request-metrics registry.

Covers status-class bucketing, latency aggregation, bounded label cardinality
(overflow into a single ``<other>`` bucket), the unmatched-route sentinel,
top-N ordering, reset isolation, that ``record`` is total (never raises) on
hostile input, and thread-safety under concurrency.
"""

from __future__ import annotations

import threading

from app.runtime_metrics import (
    UNMATCHED_TEMPLATE,
    RequestMetricsRegistry,
    status_class,
)


def _clock(values: list[float]):
    box = {"i": 0}

    def _now() -> float:
        i = box["i"]
        if i < len(values):
            box["i"] = i + 1
            return values[i]
        return values[-1]

    return _now


def test_status_class_boundaries() -> None:
    assert status_class(100) == "informational"
    assert status_class(200) == "success"
    assert status_class(204) == "success"
    assert status_class(301) == "redirect"
    assert status_class(404) == "client_error"
    assert status_class(500) == "server_error"
    assert status_class(599) == "server_error"
    # Out-of-range codes fold into a fixed key rather than a new one.
    assert status_class(0) == "other"
    assert status_class(700) == "other"


def test_records_totals_status_classes_and_latency() -> None:
    reg = RequestMetricsRegistry(now=_clock([1000.0, 1005.0]))
    reg.record(method="get", route_template="/api/x", status_code=200, duration_ms=10.0)
    reg.record(method="GET", route_template="/api/x", status_code=200, duration_ms=30.0)
    reg.record(method="POST", route_template="/api/y", status_code=500, duration_ms=100.0)
    snap = reg.snapshot()
    assert snap.total_requests == 3
    assert snap.status_classes["success"] == 2
    assert snap.status_classes["server_error"] == 1
    assert snap.average_latency_ms == round((10.0 + 30.0 + 100.0) / 3, 3)
    assert snap.max_latency_ms == 100.0
    # uptime uses the injected clock: started at 1000, snapshot at 1005.
    assert snap.uptime_seconds == 5.0


def test_method_is_normalized_and_per_route_aggregates() -> None:
    reg = RequestMetricsRegistry(now=_clock([0.0]))
    reg.record(method="get", route_template="/api/x", status_code=200, duration_ms=10.0)
    reg.record(method="GET", route_template="/api/x", status_code=404, duration_ms=20.0)
    snap = reg.snapshot()
    assert snap.tracked_routes == 1  # "get" and "GET" collapse to one label
    route = snap.top_routes[0]
    assert route.method == "GET"
    assert route.route == "/api/x"
    assert route.count == 2
    assert route.error_count == 1  # the 404
    assert route.average_latency_ms == 15.0
    assert route.max_latency_ms == 20.0


def test_unmatched_route_uses_sentinel_never_raw_path() -> None:
    reg = RequestMetricsRegistry(now=_clock([0.0]))
    # An empty template (what the middleware passes for a 404 with no matched
    # route) becomes the sentinel, not a raw path.
    reg.record(method="GET", route_template="", status_code=404, duration_ms=1.0)
    snap = reg.snapshot()
    assert snap.top_routes[0].route == UNMATCHED_TEMPLATE


def test_label_cardinality_is_bounded_with_overflow_bucket() -> None:
    reg = RequestMetricsRegistry(now=_clock([0.0]))
    # Far more distinct labels than the cap; excess must fold into one bucket.
    for i in range(600):
        reg.record(method="GET", route_template=f"/api/r{i}", status_code=200, duration_ms=1.0)
    snap = reg.snapshot(top_n=300)
    assert snap.label_overflow is True
    # tracked_routes never exceeds the cap + the single overflow bucket.
    assert snap.tracked_routes <= 257
    assert snap.total_requests == 600  # global totals stay exact regardless
    # Overflow labels fold into a single "<other>" bucket, never new keys.
    assert any(r.route == "<other>" for r in snap.top_routes)


def test_top_n_orders_by_count_and_caps() -> None:
    reg = RequestMetricsRegistry(now=_clock([0.0]))
    for _ in range(5):
        reg.record(method="GET", route_template="/hot", status_code=200, duration_ms=1.0)
    for _ in range(2):
        reg.record(method="GET", route_template="/warm", status_code=200, duration_ms=1.0)
    reg.record(method="GET", route_template="/cold", status_code=200, duration_ms=1.0)
    snap = reg.snapshot(top_n=2)
    assert [r.route for r in snap.top_routes] == ["/hot", "/warm"]


def test_negative_duration_is_clamped_and_never_raises() -> None:
    reg = RequestMetricsRegistry(now=_clock([0.0]))
    reg.record(method="GET", route_template="/x", status_code=200, duration_ms=-5.0)
    snap = reg.snapshot()
    assert snap.max_latency_ms == 0.0
    assert snap.average_latency_ms == 0.0


def test_reset_clears_all_state() -> None:
    reg = RequestMetricsRegistry(now=_clock([0.0, 0.0, 0.0]))
    reg.record(method="GET", route_template="/x", status_code=200, duration_ms=10.0)
    reg.reset()
    snap = reg.snapshot()
    assert snap.total_requests == 0
    assert snap.tracked_routes == 0
    assert snap.max_latency_ms == 0.0
    assert all(v == 0 for v in snap.status_classes.values())


def test_concurrent_records_are_counted_exactly() -> None:
    reg = RequestMetricsRegistry(now=_clock([0.0]))
    threads = [
        threading.Thread(
            target=lambda: [
                reg.record(method="GET", route_template="/x", status_code=200, duration_ms=1.0)
                for _ in range(100)
            ]
        )
        for _ in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snap = reg.snapshot()
    assert snap.total_requests == 1000
    assert snap.top_routes[0].count == 1000
