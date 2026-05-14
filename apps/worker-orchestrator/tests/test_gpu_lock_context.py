"""Tests for GpuLockContext in task_runner — renew, release-false handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tasks.task_runner import GpuLockContext


class TestGpuLockContextRenew:
    def test_renew_calls_renew_gpu_lock(self) -> None:
        ctx = GpuLockContext(task_id="run-1")
        ctx.redis_client = MagicMock()
        ctx.acquired = True
        ctx._token = "run-1:abc123"

        with patch("tasks.task_runner.renew_gpu_lock", return_value=True) as mock_renew:
            result = ctx.renew(timeout=300)

        assert result is True
        mock_renew.assert_called_once_with(ctx.redis_client, "run-1:abc123", timeout=300)

    def test_renew_returns_false_when_not_acquired(self) -> None:
        ctx = GpuLockContext(task_id="run-1")
        assert ctx.renew() is False

    def test_renew_returns_false_when_lock_lost(self) -> None:
        ctx = GpuLockContext(task_id="run-1")
        ctx.redis_client = MagicMock()
        ctx.acquired = True
        ctx._token = "run-1:abc123"

        with patch("tasks.task_runner.renew_gpu_lock", return_value=False):
            result = ctx.renew()

        assert result is False

    def test_renew_uses_shared_default_timeout(self) -> None:
        """renew() without explicit timeout must use GPU_LOCK_TIMEOUT_SECONDS."""
        from creator_provider.gpu_lock import GPU_LOCK_TIMEOUT_SECONDS

        ctx = GpuLockContext(task_id="run-1")
        ctx.redis_client = MagicMock()
        ctx.acquired = True
        ctx._token = "run-1:abc123"

        with patch("tasks.task_runner.renew_gpu_lock", return_value=True) as mock_renew:
            ctx.renew()

        mock_renew.assert_called_once_with(ctx.redis_client, "run-1:abc123", timeout=GPU_LOCK_TIMEOUT_SECONDS)


class TestGpuLockContextRelease:
    def test_released_at_set_only_on_successful_release(self) -> None:
        ctx = GpuLockContext(task_id="run-1")
        ctx.redis_client = MagicMock()
        ctx.acquired = True
        ctx._token = "run-1:abc123"

        with patch("tasks.task_runner.release_gpu_lock", return_value=True):
            ctx.release()

        assert ctx.released_at is not None

    def test_released_at_not_set_on_failed_release(self) -> None:
        """If lock was expired/stolen, released_at should remain None."""
        ctx = GpuLockContext(task_id="run-1")
        ctx.redis_client = MagicMock()
        ctx.acquired = True
        ctx._token = "run-1:abc123"

        with patch("tasks.task_runner.release_gpu_lock", return_value=False):
            ctx.release()

        assert ctx.released_at is None
        assert ctx.acquired is False  # still clears acquired flag
