import argparse
import os
import socket
import sys

from celery import Celery
from celery_app import celery_app as app


def get_target_hostname(hostname_override: str | None = None) -> str:
    if hostname_override:
        return hostname_override

    env_override = os.getenv("CELERY_WORKER_HOSTNAME") or os.getenv("WORKER_HOSTNAME")
    if env_override:
        return env_override

    return f"celery@{socket.gethostname()}"


def check_health(hostname_override: str | None = None) -> None:
    hostname = get_target_hostname(hostname_override)
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


def check_worker_health(
    redis_url: str,
    timeout_seconds: float = 3.0,
    hostname_override: str | None = None,
) -> bool:
    hostname = get_target_hostname(hostname_override)
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
    parser = argparse.ArgumentParser(description="Check Celery worker health")
    parser.add_argument("--hostname", help="Target Celery worker hostname")
    args = parser.parse_args()
    check_health(args.hostname)
