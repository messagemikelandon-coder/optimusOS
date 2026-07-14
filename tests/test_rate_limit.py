from __future__ import annotations

import asyncio
import socket
import uuid

import pytest
from redis.asyncio import Redis

from app.rate_limit import (
    RateLimitExceeded,
    RedisSlidingWindowRateLimiter,
    SlidingWindowRateLimiter,
)

_REDIS_HOST = "127.0.0.1"
_REDIS_PORT = 6379


def _redis_reachable() -> bool:
    try:
        with socket.create_connection((_REDIS_HOST, _REDIS_PORT), timeout=0.5):
            return True
    except OSError:
        return False


_redis_available = pytest.mark.skipif(
    not _redis_reachable(),
    reason="No local Redis reachable on 127.0.0.1:6379 -- these tests need a real Redis, "
    "not a mock, to prove multi-instance-safe behavior. Run `docker run -p 6379:6379 "
    "redis:7-alpine` locally (or in a CI job with a redis service container) to exercise them.",
)


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_limit() -> None:
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    await limiter.check("client")
    await limiter.check("client")
    with pytest.raises(RateLimitExceeded):
        await limiter.check("client")


@_redis_available
@pytest.mark.asyncio
async def test_redis_rate_limit_is_shared_across_independent_limiter_instances() -> None:
    """The entire point of the Redis-backed limiter: two separate limiter
    instances (each with its own Redis client, as two separate app
    processes/instances behind a load balancer would have) must share one
    combined limit for the same key -- something the old in-process-only
    limiter could never do (each instance had its own independent counter,
    silently doubling the effective limit per extra instance)."""
    key = f"multi-instance-{uuid.uuid4()}"
    instance_a = RedisSlidingWindowRateLimiter(
        redis_client=Redis(host=_REDIS_HOST, port=_REDIS_PORT), limit=3, window_seconds=60
    )
    instance_b = RedisSlidingWindowRateLimiter(
        redis_client=Redis(host=_REDIS_HOST, port=_REDIS_PORT), limit=3, window_seconds=60
    )
    await instance_a.check(key)
    await instance_b.check(key)
    await instance_a.check(key)
    with pytest.raises(RateLimitExceeded):
        await instance_b.check(key)


@_redis_available
@pytest.mark.asyncio
async def test_redis_rate_limit_uses_a_real_sliding_window() -> None:
    key = f"sliding-window-{uuid.uuid4()}"
    limiter = RedisSlidingWindowRateLimiter(
        redis_client=Redis(host=_REDIS_HOST, port=_REDIS_PORT), limit=2, window_seconds=1
    )
    await limiter.check(key)
    await limiter.check(key)
    with pytest.raises(RateLimitExceeded):
        await limiter.check(key)

    await asyncio.sleep(1.2)
    await limiter.check(key)  # the earlier requests have aged out of the window


@pytest.mark.asyncio
async def test_redis_rate_limit_falls_back_to_in_process_when_redis_is_unreachable() -> None:
    """A Redis that's down (wrong port here, standing in for an outage) must
    degrade to best-effort in-process limiting for the duration, not turn
    into either a silent bypass (no limiting at all) or a full outage of the
    public endpoints this guards."""
    key = f"fallback-{uuid.uuid4()}"
    limiter = RedisSlidingWindowRateLimiter(
        redis_client=Redis(
            host=_REDIS_HOST, port=1, socket_connect_timeout=0.5, socket_timeout=0.5
        ),
        limit=1,
        window_seconds=60,
    )
    await limiter.check(key)
    with pytest.raises(RateLimitExceeded):
        await limiter.check(key)
