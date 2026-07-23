"""Unit tests for the Phase 2B OBSERVE-only capability-decision counters."""

from __future__ import annotations

import threading

from app.capability_metrics import CapabilityDecisionCounters


def test_counts_each_known_decision() -> None:
    counters = CapabilityDecisionCounters()
    counters.record("would_allow")
    counters.record("would_allow")
    counters.record("would_deny")
    counters.record("resolution_error")
    snap = counters.snapshot()
    assert snap.decisions == {"would_allow": 2, "would_deny": 1, "resolution_error": 1}
    assert snap.total == 4


def test_unknown_decision_is_ignored_and_never_raises() -> None:
    counters = CapabilityDecisionCounters()
    # An unrecognized value must not create a new key or raise -- the key space
    # stays the fixed, bounded set of OBSERVE decisions.
    counters.record("enforce_denied")
    counters.record("")
    snap = counters.snapshot()
    assert snap.total == 0
    assert set(snap.decisions) == {"would_allow", "would_deny", "resolution_error"}


def test_reset_zeroes_counts() -> None:
    counters = CapabilityDecisionCounters()
    counters.record("would_allow")
    counters.reset()
    snap = counters.snapshot()
    assert snap.total == 0
    assert all(v == 0 for v in snap.decisions.values())


def test_concurrent_records_counted_exactly() -> None:
    counters = CapabilityDecisionCounters()
    threads = [
        threading.Thread(target=lambda: [counters.record("would_allow") for _ in range(100)])
        for _ in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert counters.snapshot().decisions["would_allow"] == 1000
