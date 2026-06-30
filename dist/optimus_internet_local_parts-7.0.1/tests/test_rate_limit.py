from __future__ import annotations

import pytest

from app.rate_limit import RateLimitExceeded, SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_limit() -> None:
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    await limiter.check("client")
    await limiter.check("client")
    with pytest.raises(RateLimitExceeded):
        await limiter.check("client")
