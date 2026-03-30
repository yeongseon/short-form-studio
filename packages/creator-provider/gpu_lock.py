import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator


GPU_LOCK_KEY = os.getenv("GPU_LOCK_KEY", "gpu:lock")

try:
    GPU_LOCK_TIMEOUT_SECONDS = int(os.getenv("GPU_LOCK_TIMEOUT_SECONDS", "600"))
except ValueError:
    GPU_LOCK_TIMEOUT_SECONDS = 600


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

    while True:
        lock_value = f"{task_id}:{int(time.time())}"
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


@asynccontextmanager
async def gpu_lock_context(
    redis_client: Any,
    task_id: str,
    timeout: int = GPU_LOCK_TIMEOUT_SECONDS,
) -> AsyncIterator[None]:
    acquire_gpu_lock(redis_client, task_id, timeout=timeout)
    try:
        yield
    finally:
        release_gpu_lock(redis_client, task_id)
