import asyncio
import unittest
from unittest.mock import Mock, patch

from creator_provider.gpu_lock import (
    GPU_LOCK_KEY,
    RELEASE_LOCK_SCRIPT,
    acquire_gpu_lock,
    acquire_gpu_lock_async,
    gpu_lock_context,
    renew_gpu_lock,
    release_gpu_lock,
)


class GpuLockTests(unittest.TestCase):
    def test_acquire_succeeds_on_first_try(self) -> None:
        redis_client = Mock()
        redis_client.set.return_value = True

        acquired = acquire_gpu_lock(redis_client, "task-1", timeout=42)

        self.assertTrue(acquired)
        redis_client.set.assert_called_once()
        call_args = redis_client.set.call_args
        self.assertEqual(call_args.kwargs["nx"], True)
        self.assertEqual(call_args.kwargs["ex"], 42)
        self.assertEqual(call_args.args[0], GPU_LOCK_KEY)
        self.assertTrue(call_args.args[1].startswith("task-1:"))

    def test_acquire_retries_when_lock_is_held(self) -> None:
        redis_client = Mock()
        redis_client.set.side_effect = [False, False, True]

        with patch("creator_provider.gpu_lock.time.sleep") as sleep_mock:
            acquired = acquire_gpu_lock(redis_client, "task-2", retry_interval=0.01, max_wait=1.0)

        self.assertTrue(acquired)
        self.assertEqual(redis_client.set.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_release_succeeds_for_holder(self) -> None:
        redis_client = Mock()
        redis_client.eval.return_value = 1

        released = release_gpu_lock(redis_client, "task-3")

        self.assertTrue(released)
        redis_client.eval.assert_called_once_with(RELEASE_LOCK_SCRIPT, 1, GPU_LOCK_KEY, "task-3:")

    def test_release_returns_false_when_not_holder(self) -> None:
        redis_client = Mock()
        redis_client.eval.return_value = 0

        released = release_gpu_lock(redis_client, "task-4")

        self.assertFalse(released)

    def test_acquire_raises_timeout_after_max_wait(self) -> None:
        redis_client = Mock()
        redis_client.set.return_value = False

        with (
            patch("creator_provider.gpu_lock.time.monotonic", side_effect=[0.0, 0.5, 1.1]),
            patch("creator_provider.gpu_lock.time.sleep"),
            self.assertRaises(TimeoutError),
        ):
            acquire_gpu_lock(redis_client, "task-timeout", retry_interval=0.01, max_wait=1.0)

    def test_double_release_safety(self) -> None:
        redis_client = Mock()
        redis_client.eval.side_effect = [1, 0]

        first_release = release_gpu_lock(redis_client, "task-5")
        second_release = release_gpu_lock(redis_client, "task-5")

        self.assertTrue(first_release)
        self.assertFalse(second_release)

    def test_context_manager_enters_and_exits_cleanly(self) -> None:
        redis_client = Mock()
        redis_client.set.return_value = True
        redis_client.eval.return_value = 1

        async def _run() -> None:
            async with gpu_lock_context(redis_client, "task-ctx", timeout=30):
                return

        asyncio.run(_run())

        redis_client.set.assert_called_once()
        redis_client.eval.assert_called_once_with(RELEASE_LOCK_SCRIPT, 1, GPU_LOCK_KEY, "task-ctx:")

    def test_renew_updates_ttl_for_current_holder(self) -> None:
        redis_client = Mock()
        redis_client.get.return_value = "task-renew:1700000000"
        redis_client.expire.return_value = True

        renewed = renew_gpu_lock(redis_client, "task-renew", timeout=120)

        self.assertTrue(renewed)
        redis_client.expire.assert_called_once_with(GPU_LOCK_KEY, 120)

    def test_renew_fails_for_non_holder(self) -> None:
        redis_client = Mock()
        redis_client.get.return_value = "other-task:1700000000"

        renewed = renew_gpu_lock(redis_client, "task-renew", timeout=120)

        self.assertFalse(renewed)
        redis_client.expire.assert_not_called()

    def test_async_acquire_yields_control_while_waiting(self) -> None:
        redis_client = Mock()
        redis_client.set.side_effect = [False, False, True]
        ticks: list[int] = []

        async def ticker() -> None:
            for i in range(5):
                ticks.append(i)
                await asyncio.sleep(0)

        async def run_test() -> None:
            await asyncio.gather(
                acquire_gpu_lock_async(
                    redis_client, "task-async", retry_interval=0.001, max_wait=1.0
                ),
                ticker(),
            )

        asyncio.run(run_test())
        self.assertGreaterEqual(len(ticks), 3)


if __name__ == "__main__":
    unittest.main()
