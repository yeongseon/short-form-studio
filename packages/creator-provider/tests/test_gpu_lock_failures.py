"""GPU lock failure path tests.

Covers:
- Lock acquisition timeout
- Lock release when task doesn't own it
- Async context manager cleanup on exception
- Successful acquire/release cycle
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from creator_provider.gpu_lock import (
    acquire_gpu_lock,
    release_gpu_lock,
    gpu_lock_context,
)


class TestAcquireGPULock:
    def test_acquire_succeeds_first_try(self):
        redis = MagicMock()
        redis.set.return_value = True
        result = acquire_gpu_lock(redis, "task-1", timeout=60)
        assert result is True
        redis.set.assert_called_once()

    def test_acquire_timeout_raises(self):
        redis = MagicMock()
        redis.set.return_value = False  # always fails to acquire
        with pytest.raises(TimeoutError, match="Timed out"):
            acquire_gpu_lock(redis, "task-1", timeout=60, max_wait=0.1, retry_interval=0.05)

    def test_acquire_retries_then_succeeds(self):
        redis = MagicMock()
        redis.set.side_effect = [False, False, True]  # fail twice, then succeed
        result = acquire_gpu_lock(redis, "task-1", timeout=60, retry_interval=0.01, max_wait=5.0)
        assert result is True
        assert redis.set.call_count == 3


class TestReleaseGPULock:
    def test_release_succeeds(self):
        redis = MagicMock()
        redis.eval.return_value = 1
        result = release_gpu_lock(redis, "task-1")
        assert result is True

    def test_release_fails_not_owner(self):
        redis = MagicMock()
        redis.eval.return_value = 0
        result = release_gpu_lock(redis, "task-1")
        assert result is False

    def test_release_script_uses_correct_key_prefix(self):
        redis = MagicMock()
        redis.eval.return_value = 1
        release_gpu_lock(redis, "my-task-id")
        args = redis.eval.call_args
        assert "my-task-id:" in str(args)


class TestGPULockContextManager:
    @pytest.mark.asyncio
    async def test_context_acquires_and_releases(self):
        redis = MagicMock()
        redis.set.return_value = True
        redis.eval.return_value = 1

        async with gpu_lock_context(redis, "task-1", timeout=60):
            pass  # lock held

        redis.set.assert_called_once()
        redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_releases_on_exception(self):
        redis = MagicMock()
        redis.set.return_value = True
        redis.eval.return_value = 1

        with pytest.raises(ValueError, match="boom"):
            async with gpu_lock_context(redis, "task-1", timeout=60):
                raise ValueError("boom")

        # Lock must still be released
        redis.eval.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_propagates_timeout(self):
        redis = MagicMock()
        redis.set.return_value = False

        with patch("creator_provider.gpu_lock.acquire_gpu_lock", side_effect=TimeoutError("Timed out")):
            with pytest.raises(TimeoutError):
                async with gpu_lock_context(redis, "task-1", timeout=60):
                    pass  # should never reach here
