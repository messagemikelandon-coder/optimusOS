"""OBSERVE-only capability-decision counters (Phase 2B).

A bounded, thread-safe tally of what the ADR-022 capability gate (OBSERVE mode)
*would* have decided, so a platform-support operator can see the pilot's
allow/deny/resolution-error distribution in aggregate -- the same signal the
per-request ``CAPABILITY_OBSERVED`` log event carries, rolled up into fixed
counters that need no log aggregator to read.

This is purely additive telemetry layered beside the existing gate event. It
never changes any request outcome, is OBSERVE-only, and references no
enforcement: the counter keys are exactly the three OBSERVE decisions
(``would_allow`` / ``would_deny`` / ``resolution_error``). There is a fixed,
enumerable set of keys, so the store is bounded by construction.

``record`` is total (cannot raise) so incrementing a counter can never disturb
the gate it observes. A single process-wide instance (``capability_metrics``)
is shared across requests; ``reset()`` exists only for test isolation.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

# The three OBSERVE decisions the gate can reach. Fixed and enumerable: this is
# the whole key space, so the counter map can never grow unbounded. Kept as
# plain strings (matching CapabilityDecision values) so this leaf module has no
# import dependency on the gate and cannot introduce an import cycle.
_DECISIONS = ("would_allow", "would_deny", "resolution_error")


@dataclass(frozen=True)
class CapabilityMetricsSnapshot:
    """Cumulative OBSERVE-mode decision counts for this process."""

    total: int
    decisions: dict[str, int]


class CapabilityDecisionCounters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[str, int] = dict.fromkeys(_DECISIONS, 0)

    def reset(self) -> None:
        """Zero all counters (test-only; a real process shares one instance)."""
        with self._lock:
            self._counts = dict.fromkeys(_DECISIONS, 0)

    def record(self, decision: str) -> None:
        """Increment the counter for one OBSERVE decision. Total by
        construction: an unrecognized value is ignored rather than creating a
        new key, so this can never raise and never grow the key space."""
        if decision not in self._counts:
            return
        with self._lock:
            self._counts[decision] += 1

    def snapshot(self) -> CapabilityMetricsSnapshot:
        with self._lock:
            counts = dict(self._counts)
        return CapabilityMetricsSnapshot(total=sum(counts.values()), decisions=counts)


# Process-wide instance shared across requests. Tests call reset() for
# isolation; a real process never does.
capability_metrics = CapabilityDecisionCounters()
