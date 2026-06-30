from __future__ import annotations

import logging
import signal
import time

from app.config import Settings
from app.main import _tcp_dependency_ready

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("optimus.worker")
_running = True


def _stop(_signum: int, _frame: object) -> None:
    global _running
    _running = False


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    settings = Settings()
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
        time.sleep(60)
    logger.info("OptimusOS worker stopped")


if __name__ == "__main__":
    main()
