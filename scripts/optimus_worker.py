from __future__ import annotations

import logging
import signal
import time

from redis import Redis
from redis.exceptions import RedisError

from app.config import Settings
from app.main import _tcp_dependency_ready

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("optimus.worker")
_running = True


def _stop(_signum: int, _frame: object) -> None:
    global _running
    _running = False


def _write_heartbeat(client: Redis, key: str, ttl_seconds: int, now: float) -> bool:
    """Write a single bounded heartbeat: the key holds one epoch second and
    expires after ``ttl_seconds`` (validated >= 2x the write interval, so a
    live worker's key survives across beats even with the loop's dependency-probe
    latency). Read by the support operational summary to infer worker liveness.
    No job/customer data is ever written -- only the timestamp. Fail-safe: a
    Redis error is logged (without the URL) and swallowed so a heartbeat outage
    never crashes the worker loop."""
    try:
        client.set(key, str(now), ex=ttl_seconds)
        return True
    except (RedisError, OSError):
        logger.warning("Worker heartbeat write failed (Redis unavailable)")
        return False


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    settings = Settings()
    interval = settings.worker_heartbeat_interval_seconds
    heartbeat_key = settings.worker_heartbeat_redis_key
    heartbeat_ttl = settings.worker_heartbeat_ttl_seconds
    # A dedicated, short-timeout client for the heartbeat write. Constructed once
    # and reused; a connection error surfaces per-write and is swallowed there.
    heartbeat_client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=settings.dependency_probe_timeout_seconds,
        socket_timeout=settings.dependency_probe_timeout_seconds,
    )
    logger.info("OptimusOS worker started")
    while _running:
        postgres_ready = _tcp_dependency_ready(settings.database_url, 5432)
        redis_ready = _tcp_dependency_ready(settings.redis_url, 6379)
        if postgres_ready and redis_ready:
            logger.info("Worker dependency check passed")
        else:
            logger.warning(
                "Worker dependency check degraded postgres=%s redis=%s",
                postgres_ready,
                redis_ready,
            )
        _write_heartbeat(heartbeat_client, heartbeat_key, heartbeat_ttl, time.time())
        # Beat on the heartbeat interval, not the old fixed 60s, so the key's TTL
        # (>= interval) always covers the gap between writes. Poll _running each
        # second so SIGTERM/SIGINT stops promptly instead of after a long sleep.
        for _ in range(max(1, interval)):
            if not _running:
                break
            time.sleep(1)
    logger.info("OptimusOS worker stopped")


if __name__ == "__main__":
    main()
