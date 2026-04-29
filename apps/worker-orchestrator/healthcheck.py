import socket
import sys

from celery import Celery
from celery_app import celery_app as app


def check_health() -> None:
    hostname = f"celery@{socket.gethostname()}"
    response = app.control.ping(destination=[hostname], timeout=5.0)

    if not response:
        print(f"UNHEALTHY: No response from {hostname}")
        sys.exit(1)

    for entry in response:
        if hostname in entry and entry[hostname].get("ok") == "pong":
            print(f"HEALTHY: {hostname} responded")
            sys.exit(0)

    print(f"UNHEALTHY: {hostname} did not respond correctly")
    sys.exit(1)


def check_worker_health(redis_url: str, timeout_seconds: float = 3.0) -> bool:
    hostname = f"celery@{socket.gethostname()}"
    healthcheck_app = Celery("worker-healthcheck", broker=redis_url, backend=redis_url)
    if hasattr(healthcheck_app.control, "ping"):
        response = healthcheck_app.control.ping(destination=[hostname], timeout=timeout_seconds)
    else:
        inspect = healthcheck_app.control.inspect(timeout=timeout_seconds)
        response = inspect.ping()

    if isinstance(response, dict):
        return any(worker_result.get("ok") == "pong" for worker_result in response.values())

    if not response:
        return False

    for entry in response:
        if hostname in entry and entry[hostname].get("ok") == "pong":
            return True
    return False


if __name__ == "__main__":
    check_health()
