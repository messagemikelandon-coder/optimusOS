from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class RateLimitExceeded(RuntimeError):
    pass


class SlidingWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: float = 60.0) -> None:
        self._limit = limit
        self._window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    async def check(self, key: str) -> None:
        now = time.monotonic()
        cutoff = now - self._window
        async with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self._limit:
                raise RateLimitExceeded("Estimate request limit exceeded. Try again shortly.")
            events.append(now)
