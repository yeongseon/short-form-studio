import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gpu_lock import GPU_LOCK_KEY, RELEASE_LOCK_SCRIPT, acquire_gpu_lock, gpu_lock_context, release_gpu_lock


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

        with patch("gpu_lock.time.sleep") as sleep_mock:
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

        with patch("gpu_lock.time.monotonic", side_effect=[0.0, 0.5, 1.1]), patch("gpu_lock.time.sleep"):
            with self.assertRaises(TimeoutError):
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


if __name__ == "__main__":
    unittest.main()
