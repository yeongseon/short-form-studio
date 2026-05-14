import asyncio
from unittest.mock import Mock, patch

import pytest

from tasks.task_runner import GpuLockContext


@pytest.mark.asyncio
async def test_acquire_starts_renewal() -> None:
    redis_client = Mock()
    lock_ctx = GpuLockContext("task-1")
    sleep_gate = asyncio.Event()
    real_sleep = asyncio.sleep

    async def _sleep(_: float) -> None:
        await sleep_gate.wait()

    with (
        patch("tasks.task_runner._get_redis_client", return_value=redis_client),
        patch("tasks.task_runner.acquire_gpu_lock", return_value="task-1:token"),
        patch("tasks.task_runner.asyncio.sleep", side_effect=_sleep),
    ):
        lock_ctx.acquire()
        await real_sleep(0)
        assert lock_ctx._renewal_task is not None
        assert not lock_ctx._renewal_task.done()
        lock_ctx.stop_auto_renewal()
        sleep_gate.set()


@pytest.mark.asyncio
async def test_lock_lost_flag_on_renewal_failure() -> None:
    redis_client = Mock()
    lock_ctx = GpuLockContext("task-2")
    real_sleep = asyncio.sleep

    async def _no_sleep(_: float) -> None:
        return

    with (
        patch("tasks.task_runner._get_redis_client", return_value=redis_client),
        patch("tasks.task_runner.acquire_gpu_lock", return_value="task-2:token"),
        patch("tasks.task_runner.renew_gpu_lock", return_value=False),
        patch("tasks.task_runner.asyncio.sleep", side_effect=_no_sleep),
    ):
        lock_ctx.acquire()
        for _ in range(100):
            if lock_ctx.lock_lost:
                break
            await real_sleep(0.001)
        assert lock_ctx.lock_lost is True
        assert lock_ctx.acquired is False


@pytest.mark.asyncio
async def test_stop_auto_renewal_cancels_task() -> None:
    redis_client = Mock()
    lock_ctx = GpuLockContext("task-3")
    sleep_gate = asyncio.Event()
    real_sleep = asyncio.sleep

    async def _sleep(_: float) -> None:
        await sleep_gate.wait()

    with (
        patch("tasks.task_runner._get_redis_client", return_value=redis_client),
        patch("tasks.task_runner.acquire_gpu_lock", return_value="task-3:token"),
        patch("tasks.task_runner.asyncio.sleep", side_effect=_sleep),
    ):
        lock_ctx.acquire()
        await real_sleep(0)
        assert lock_ctx._renewal_task is not None
        task = lock_ctx._renewal_task
        lock_ctx.stop_auto_renewal()
        sleep_gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_release_raises_when_lock_lost() -> None:
    """release() must raise RuntimeError if lock was lost during execution (fail-closed)."""
    redis_client = Mock()
    lock_ctx = GpuLockContext("task-4")
    real_sleep = asyncio.sleep

    async def _no_sleep(_: float) -> None:
        return

    with (
        patch("tasks.task_runner._get_redis_client", return_value=redis_client),
        patch("tasks.task_runner.acquire_gpu_lock", return_value="task-4:token"),
        patch("tasks.task_runner.renew_gpu_lock", return_value=False),
        patch("tasks.task_runner.release_gpu_lock", return_value=True),
        patch("tasks.task_runner.asyncio.sleep", side_effect=_no_sleep),
    ):
        lock_ctx.acquire()
        # Wait for renewal loop to detect failure
        for _ in range(100):
            if lock_ctx.lock_lost:
                break
            await real_sleep(0.001)
        assert lock_ctx.lock_lost is True
        # release() should raise RuntimeError because lock was lost
        with pytest.raises(RuntimeError, match="GPU lock was lost"):
            lock_ctx.release()
