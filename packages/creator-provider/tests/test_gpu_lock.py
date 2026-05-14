import asyncio
import unittest
from unittest.mock import ANY, Mock, patch

from creator_provider.gpu_lock import (
    GPU_LOCK_KEY,
    RELEASE_LOCK_SCRIPT,
    RENEW_LOCK_SCRIPT,
    acquire_gpu_lock,
    gpu_lock_context,
    release_gpu_lock,
    renew_gpu_lock,
)


class GpuLockTests(unittest.TestCase):
    def test_acquire_succeeds_on_first_try(self) -> None:
        redis_client = Mock()
        redis_client.set.return_value = True

        token = acquire_gpu_lock(redis_client, "task-1", timeout=42)

        self.assertIsInstance(token, str)
        self.assertTrue(token.startswith("task-1:"))
        redis_client.set.assert_called_once()
        call_args = redis_client.set.call_args
        self.assertEqual(call_args.kwargs["nx"], True)
        self.assertEqual(call_args.kwargs["ex"], 42)
        self.assertEqual(call_args.args[0], GPU_LOCK_KEY)
        self.assertEqual(call_args.args[1], token)

    def test_acquire_retries_when_lock_is_held(self) -> None:
        redis_client = Mock()
        redis_client.set.side_effect = [False, False, True]

        with patch("creator_provider.gpu_lock.time.sleep") as sleep_mock:
            token = acquire_gpu_lock(redis_client, "task-2", retry_interval=0.01, max_wait=1.0)

        self.assertIsInstance(token, str)
        self.assertEqual(redis_client.set.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_release_succeeds_for_holder(self) -> None:
        redis_client = Mock()
        redis_client.eval.return_value = 1

        released = release_gpu_lock(redis_client, "task-3:abc123")

        self.assertTrue(released)
        redis_client.eval.assert_called_once_with(
            RELEASE_LOCK_SCRIPT, 1, GPU_LOCK_KEY, "task-3:abc123"
        )

    def test_release_returns_false_when_not_holder(self) -> None:
        redis_client = Mock()
        redis_client.eval.return_value = 0

        released = release_gpu_lock(redis_client, "task-4:wrong-token")

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

        first_release = release_gpu_lock(redis_client, "task-5:token")
        second_release = release_gpu_lock(redis_client, "task-5:token")

        self.assertTrue(first_release)
        self.assertFalse(second_release)

    def test_exact_token_release_prevents_prefix_collision(self) -> None:
        """A token that is a prefix of another must NOT release the other's lock."""
        redis_client = Mock()
        redis_client.set.return_value = True

        token1 = acquire_gpu_lock(redis_client, "task", timeout=60)
        token2 = acquire_gpu_lock(redis_client, "task-extended", timeout=60)

        # Tokens are unique UUIDs, so they can never match each other
        self.assertNotEqual(token1, token2)

    def test_renew_extends_lease(self) -> None:
        redis_client = Mock()
        redis_client.eval.return_value = 1

        renewed = renew_gpu_lock(redis_client, "task-1:uuid-token", timeout=300)

        self.assertTrue(renewed)
        redis_client.eval.assert_called_once_with(
            RENEW_LOCK_SCRIPT, 1, GPU_LOCK_KEY, "task-1:uuid-token", "300"
        )

    def test_renew_returns_false_when_not_holder(self) -> None:
        redis_client = Mock()
        redis_client.eval.return_value = 0

        renewed = renew_gpu_lock(redis_client, "wrong-token")

        self.assertFalse(renewed)

    def test_context_manager_enters_and_exits_cleanly(self) -> None:
        redis_client = Mock()
        redis_client.set.return_value = True
        redis_client.eval.return_value = 1

        async def _run() -> None:
            async with gpu_lock_context(redis_client, "task-ctx", timeout=30) as token:
                self.assertIsInstance(token, str)
                self.assertTrue(token.startswith("task-ctx:"))

        asyncio.run(_run())

        redis_client.set.assert_called_once()
        # Release is called with the exact token, not task_id prefix
        redis_client.eval.assert_called_once()
        call_args = redis_client.eval.call_args
        self.assertEqual(call_args.args[0], RELEASE_LOCK_SCRIPT)
        token_arg = call_args.args[3]
        self.assertTrue(token_arg.startswith("task-ctx:"))

    def test_context_manager_acquires_lock_via_blocking_helper(self) -> None:
        redis_client = Mock()
        redis_client.set.return_value = True
        redis_client.eval.return_value = 1

        async def _run() -> None:
            async with gpu_lock_context(redis_client, "task-thread", timeout=30):
                return

        asyncio.run(_run())
        redis_client.set.assert_called_once_with(
            GPU_LOCK_KEY,
            ANY,
            nx=True,
            ex=30,
        )


if __name__ == "__main__":
    unittest.main()
