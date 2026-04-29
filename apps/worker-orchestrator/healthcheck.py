from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from celery import Celery


def check_worker_health(redis_url: str, timeout_seconds: float = 3.0) -> bool:
    app = Celery("worker-healthcheck", broker=redis_url, backend=redis_url)
    inspect = app.control.inspect(timeout=timeout_seconds)
    response: Any = inspect.ping()
    if not isinstance(response, dict) or not response:
        return False
    return any(worker_result.get("ok") == "pong" for worker_result in response.values())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Celery worker health with inspect ping")
    parser.add_argument(
        "--redis-url",
        default=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        help="Celery broker/backend Redis URL (default: REDIS_URL env)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=3.0,
        help="Inspect ping timeout in seconds",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    is_healthy = check_worker_health(args.redis_url, args.timeout_seconds)
    if is_healthy:
        print("Worker health check passed")
        return 0

    print("Worker health check failed: no Celery worker responded to ping")
    return 1


if __name__ == "__main__":
    sys.exit(main())
