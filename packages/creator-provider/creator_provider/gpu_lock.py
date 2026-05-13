import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

GPU_LOCK_KEY = os.getenv("GPU_LOCK_KEY", "gpu:lock")


def _parse_timeout_seconds() -> int:
    raw = os.getenv("GPU_LOCK_TIMEOUT_SECONDS", "600")
    try:
        return int(raw)
    except ValueError:
        return 600


GPU_LOCK_TIMEOUT_SECONDS = _parse_timeout_seconds()


RELEASE_LOCK_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if not current then
    return 0
end

if string.sub(current, 1, string.len(ARGV[1])) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end

return 0
"""


def acquire_gpu_lock(
    redis_client: Any,
    task_id: str,
    timeout: int = GPU_LOCK_TIMEOUT_SECONDS,
    retry_interval: float = 2.0,
    max_wait: float = 300.0,
) -> bool:
    start_time = time.monotonic()
    backoff = retry_interval
    lease_expires_at = int(time.time()) + timeout

    while True:
        lock_value = f"{task_id}:{lease_expires_at}"
        acquired = redis_client.set(GPU_LOCK_KEY, lock_value, nx=True, ex=timeout)
        if acquired:
            return True

        elapsed = time.monotonic() - start_time
        if elapsed >= max_wait:
            raise TimeoutError(f"Timed out acquiring GPU lock for task '{task_id}'")

        sleep_for = min(backoff, max_wait - elapsed)
        if sleep_for > 0:
            time.sleep(sleep_for)
        backoff = min(backoff * 2, 30.0)


def release_gpu_lock(redis_client: Any, task_id: str) -> bool:
    released = redis_client.eval(RELEASE_LOCK_SCRIPT, 1, GPU_LOCK_KEY, f"{task_id}:")
    return bool(released)


def renew_gpu_lock(
    redis_client: Any, task_id: str, timeout: int = GPU_LOCK_TIMEOUT_SECONDS
) -> bool:
    current = redis_client.get(GPU_LOCK_KEY)
    if current is None:
        return False
    if isinstance(current, bytes):
        current = current.decode("utf-8")
    if not isinstance(current, str) or not current.startswith(f"{task_id}:"):
        return False
    return bool(redis_client.expire(GPU_LOCK_KEY, timeout))


async def acquire_gpu_lock_async(
    redis_client: Any,
    task_id: str,
    timeout: int = GPU_LOCK_TIMEOUT_SECONDS,
    retry_interval: float = 2.0,
    max_wait: float = 300.0,
) -> bool:
    start_time = time.monotonic()
    backoff = retry_interval
    lease_expires_at = int(time.time()) + timeout

    while True:
        lock_value = f"{task_id}:{lease_expires_at}"
        acquired = redis_client.set(GPU_LOCK_KEY, lock_value, nx=True, ex=timeout)
        if acquired:
            return True

        elapsed = time.monotonic() - start_time
        if elapsed >= max_wait:
            raise TimeoutError(f"Timed out acquiring GPU lock for task '{task_id}'")

        sleep_for = min(backoff, max_wait - elapsed)
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)
        backoff = min(backoff * 2, 30.0)


@asynccontextmanager
async def gpu_lock_context(
    redis_client: Any,
    task_id: str,
    timeout: int = GPU_LOCK_TIMEOUT_SECONDS,
) -> AsyncIterator[None]:
    await acquire_gpu_lock_async(redis_client, task_id, timeout=timeout)
    try:
        yield
    finally:
        release_gpu_lock(redis_client, task_id)
