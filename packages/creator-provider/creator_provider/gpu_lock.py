import asyncio
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

GPU_LOCK_KEY = os.getenv("GPU_LOCK_KEY", "gpu:lock")
logger = logging.getLogger(__name__)


def _parse_timeout_seconds() -> int:
    raw = os.getenv("GPU_LOCK_TIMEOUT_SECONDS", "600")
    try:
        return int(raw)
    except ValueError:
        return 600


GPU_LOCK_TIMEOUT_SECONDS = _parse_timeout_seconds()


# Release only if the current value matches the token exactly.
RELEASE_LOCK_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

# Renew lease only if the current value matches the token exactly.
RENEW_LOCK_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""


def acquire_gpu_lock(
    redis_client: Any,
    task_id: str,
    timeout: int = GPU_LOCK_TIMEOUT_SECONDS,
    retry_interval: float = 2.0,
    max_wait: float = 300.0,
) -> str:
    """Acquire the GPU lock and return the opaque lock token.

    Returns the unique token that must be passed to ``release_gpu_lock``
    and ``renew_gpu_lock``.  Raises ``TimeoutError`` if the lock cannot be
    acquired within *max_wait* seconds.
    """
    start_time = time.monotonic()
    backoff = retry_interval
    token = f"{task_id}:{uuid.uuid4().hex}"

    while True:
        acquired = redis_client.set(GPU_LOCK_KEY, token, nx=True, ex=timeout)
        if acquired:
            return token

        elapsed = time.monotonic() - start_time
        if elapsed >= max_wait:
            raise TimeoutError(f"Timed out acquiring GPU lock for task '{task_id}'")

        sleep_for = min(backoff, max_wait - elapsed)
        if sleep_for > 0:
            time.sleep(sleep_for)
        backoff = min(backoff * 2, 30.0)


def release_gpu_lock(redis_client: Any, token: str) -> bool:
    """Release the GPU lock if *token* matches the current holder exactly."""
    released = redis_client.eval(RELEASE_LOCK_SCRIPT, 1, GPU_LOCK_KEY, token)
    return bool(released)


def renew_gpu_lock(
    redis_client: Any,
    token: str,
    timeout: int = GPU_LOCK_TIMEOUT_SECONDS,
) -> bool:
    """Extend the GPU lock lease if *token* still holds it.

    Returns ``True`` if the lease was extended, ``False`` if the lock is no
    longer held by this token.
    """
    renewed = redis_client.eval(RENEW_LOCK_SCRIPT, 1, GPU_LOCK_KEY, token, str(timeout))
    return bool(renewed)


@asynccontextmanager
async def gpu_lock_context(
    redis_client: Any,
    task_id: str,
    timeout: int = GPU_LOCK_TIMEOUT_SECONDS,
) -> AsyncIterator[str]:
    """Async context manager that acquires, optionally renews, and releases the GPU lock.

    Yields the opaque lock token so callers can renew the lease for
    long-running operations via ``renew_gpu_lock``.

    Starts a background renewal task that extends the lease at half the timeout
    interval to prevent expiry during long-running GPU operations.
    """
    lock_lost = False
    token = await asyncio.to_thread(acquire_gpu_lock, redis_client, task_id, timeout)
    renewal_interval = max(timeout // 2, 1)

    async def _auto_renew() -> None:
        nonlocal lock_lost
        while True:
            await asyncio.sleep(renewal_interval)
            try:
                ok = await asyncio.to_thread(renew_gpu_lock, redis_client, token, timeout)
                if not ok:
                    lock_lost = True
                    logger.warning("GPU lock renewal failed for task %s", task_id)
                    break
            except Exception:
                lock_lost = True
                logger.warning("GPU lock renewal raised for task %s", task_id, exc_info=True)
                break

    renewal_task = asyncio.create_task(_auto_renew())
    body_failed = False
    try:
        yield token
    except Exception:
        body_failed = True
        raise
    finally:
        renewal_task.cancel()
        try:
            await renewal_task
        except asyncio.CancelledError:
            pass
        release_gpu_lock(redis_client, token)
    if lock_lost and not body_failed:
        logger.warning("GPU lock was lost during execution for task %s", task_id)
        raise RuntimeError(f"GPU lock lost during execution for task '{task_id}'")
