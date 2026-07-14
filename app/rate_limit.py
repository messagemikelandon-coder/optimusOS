from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger("optimus")


class RateLimitExceeded(RuntimeError):
    pass


class RateLimiter(Protocol):
    @property
    def limit(self) -> int: ...

    async def check(self, key: str) -> None: ...


class SlidingWindowRateLimiter:
    """In-process sliding window. Single-instance only -- kept as the
    Redis-backed limiter's fallback for when Redis is briefly unreachable,
    and directly usable where a real Redis isn't available (e.g. tests)."""

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


class RedisSlidingWindowRateLimiter:
    """Multi-instance-safe sliding window, backed by a Redis sorted set per
    key (score = request timestamp). Atomic per check via a Redis pipeline
    -- Redis processes each client's pipelined commands as one uninterrupted
    batch, so concurrent requests across multiple app instances can't
    interleave mid-check. Falls back to an in-process limiter (best-effort,
    not multi-instance-safe) only for the duration of a Redis outage, rather
    than either failing the request open (no protection at all) or closed
    (a full outage of a public endpoint over a transient Redis hiccup)."""

    def __init__(self, *, redis_client: Redis, limit: int, window_seconds: float = 60.0) -> None:
        self._redis = redis_client
        self._limit = limit
        self._window = window_seconds
        self._fallback = SlidingWindowRateLimiter(limit=limit, window_seconds=window_seconds)

    @property
    def limit(self) -> int:
        return self._limit

    async def check(self, key: str) -> None:
        redis_key = f"optimus:ratelimit:{key}"
        now = time.time()
        cutoff = now - self._window
        member = f"{now}:{uuid.uuid4()}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(redis_key, 0, cutoff)
                pipe.zadd(redis_key, {member: now})
                pipe.zcard(redis_key)
                pipe.expire(redis_key, int(self._window) + 1)
                results = await pipe.execute()
            count = results[2]
        except RedisError:
            logger.warning(
                "Rate limiter Redis unavailable; falling back to in-process "
                "limiting for this request (not multi-instance-safe until "
                "Redis recovers)."
            )
            await self._fallback.check(key)
            return

        if count > self._limit:
            with contextlib.suppress(RedisError):
                await self._redis.zrem(redis_key, member)
            raise RateLimitExceeded("Estimate request limit exceeded. Try again shortly.")
