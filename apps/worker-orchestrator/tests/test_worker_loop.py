"""Tests for per-process long-lived event loop (worker_loop module).

Verifies that:
1. The event loop persists across multiple run_in_worker_loop() calls
2. The DB pool is reused (same loop = same pool)
3. Worker process init/shutdown signals create/close the loop properly
4. Fallback loop creation works outside Celery worker context
5. Pool is closed during shutdown
6. Orphaned background tasks do NOT leak across calls (isolation)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import worker_loop


@pytest.fixture(autouse=True)
def _reset_worker_loop():
    """Ensure clean state before/after each test."""
    worker_loop.reset_worker_loop()
    yield
    worker_loop.reset_worker_loop()


class TestGetWorkerLoop:
    def test_creates_loop_on_first_call(self) -> None:
        loop = worker_loop.get_worker_loop()
        assert loop is not None
        assert not loop.is_closed()

    def test_returns_same_loop_on_subsequent_calls(self) -> None:
        loop1 = worker_loop.get_worker_loop()
        loop2 = worker_loop.get_worker_loop()
        assert loop1 is loop2

    def test_creates_new_loop_if_previous_closed(self) -> None:
        loop1 = worker_loop.get_worker_loop()
        loop1.close()
        loop2 = worker_loop.get_worker_loop()
        assert loop2 is not loop1
        assert not loop2.is_closed()


class TestRunInWorkerLoop:
    def test_runs_coroutine_and_returns_result(self) -> None:
        async def add(a: int, b: int) -> int:
            return a + b

        result = worker_loop.run_in_worker_loop(add(3, 4))
        assert result == 7

    def test_preserves_loop_across_multiple_calls(self) -> None:
        """The key property: multiple tasks reuse the same event loop."""
        loops: list[asyncio.AbstractEventLoop] = []

        async def capture_loop() -> None:
            loops.append(asyncio.get_running_loop())

        worker_loop.run_in_worker_loop(capture_loop())
        worker_loop.run_in_worker_loop(capture_loop())
        worker_loop.run_in_worker_loop(capture_loop())

        assert len(loops) == 3
        assert loops[0] is loops[1]
        assert loops[1] is loops[2]

    def test_pool_reused_across_calls(self) -> None:
        """asyncpg pool should be reused because event loop stays the same."""
        import creator_service.db as db_mod

        pool_ids: list[int] = []

        async def capture_pool_id() -> None:
            pool = await db_mod.get_pool()
            pool_ids.append(id(pool))

        mock_pool = AsyncMock()
        with patch.object(db_mod, "asyncpg") as mock_asyncpg, \
             patch.dict("os.environ", {"DATABASE_URL": "postgres://test:test@localhost/test"}):
            mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
            # Reset db module state
            db_mod._pool = None
            db_mod._pool_loop = None

            worker_loop.run_in_worker_loop(capture_pool_id())
            worker_loop.run_in_worker_loop(capture_pool_id())

            assert len(pool_ids) == 2
            assert pool_ids[0] == pool_ids[1]
            # Pool created only once
            assert mock_asyncpg.create_pool.await_count == 1

            # Cleanup
            db_mod._pool = None
            db_mod._pool_loop = None

    def test_propagates_exceptions(self) -> None:
        async def fail() -> None:
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            worker_loop.run_in_worker_loop(fail())

    def test_orphan_tasks_cancelled_between_calls(self) -> None:
        """Background tasks from one call must NOT leak into the next."""
        orphan_ran = False

        async def spawn_orphan() -> str:
            async def orphan_work() -> None:
                nonlocal orphan_ran
                await asyncio.sleep(0.1)
                orphan_ran = True

            asyncio.create_task(orphan_work())
            return "spawned"

        result = worker_loop.run_in_worker_loop(spawn_orphan())
        assert result == "spawned"

        # The orphan should have been cancelled by cleanup
        async def noop() -> None:
            await asyncio.sleep(0)  # Yield to let any surviving tasks run

        worker_loop.run_in_worker_loop(noop())
        assert not orphan_ran, "Orphan task leaked across run_in_worker_loop calls"

    def test_cleanup_runs_after_exception(self) -> None:
        """Orphan cleanup must also happen when the main coroutine raises."""
        orphan_ran = False

        async def spawn_and_fail() -> None:
            async def orphan_work() -> None:
                nonlocal orphan_ran
                await asyncio.sleep(0.1)
                orphan_ran = True

            asyncio.create_task(orphan_work())
            raise RuntimeError("intentional failure")

        with pytest.raises(RuntimeError, match="intentional failure"):
            worker_loop.run_in_worker_loop(spawn_and_fail())

        async def noop() -> None:
            await asyncio.sleep(0)

        worker_loop.run_in_worker_loop(noop())
        assert not orphan_ran, "Orphan task leaked after exception"


class TestCancelPendingTasks:
    def test_cancels_all_pending_tasks(self) -> None:
        loop = worker_loop.get_worker_loop()

        results: list[str] = []

        async def bg_task(name: str) -> None:
            try:
                await asyncio.sleep(10)
                results.append(name)
            except asyncio.CancelledError:
                pass

        async def spawn_tasks() -> None:
            asyncio.create_task(bg_task("a"))
            asyncio.create_task(bg_task("b"))

        loop.run_until_complete(spawn_tasks())
        worker_loop._cancel_pending_tasks(loop)

        assert len(results) == 0

    def test_noop_when_no_pending(self) -> None:
        loop = worker_loop.get_worker_loop()
        worker_loop._cancel_pending_tasks(loop)  # should not raise


class TestWorkerProcessInitSignal:
    def test_creates_new_loop(self) -> None:
        worker_loop._init_worker_loop()
        loop = worker_loop._worker_loop
        assert loop is not None
        assert not loop.is_closed()

    def test_replaces_existing_loop(self) -> None:
        old_loop = worker_loop.get_worker_loop()
        worker_loop._init_worker_loop()
        new_loop = worker_loop._worker_loop
        assert new_loop is not old_loop

    def test_closes_pre_existing_fallback_loop(self) -> None:
        """If a fallback loop exists, _init_worker_loop should close it."""
        fallback = worker_loop.get_worker_loop()
        assert not fallback.is_closed()
        worker_loop._init_worker_loop()
        assert fallback.is_closed()


class TestWorkerProcessShutdownSignal:
    def test_closes_loop(self) -> None:
        worker_loop._init_worker_loop()
        loop = worker_loop._worker_loop
        assert loop is not None

        with patch("creator_service.db.close_pool", new_callable=AsyncMock) as mock_close:
            worker_loop._shutdown_worker_loop()

        assert worker_loop._worker_loop is None
        assert loop.is_closed()
        mock_close.assert_awaited_once()

    def test_noop_when_no_loop(self) -> None:
        """Should not raise when there's no loop to close."""
        worker_loop._worker_loop = None
        worker_loop._shutdown_worker_loop()  # should not raise

    def test_handles_pool_close_failure(self) -> None:
        worker_loop._init_worker_loop()

        with patch("creator_service.db.close_pool", new_callable=AsyncMock) as mock_close:
            mock_close.side_effect = RuntimeError("pool close failed")
            # Should not raise
            worker_loop._shutdown_worker_loop()

        assert worker_loop._worker_loop is None


class TestResetWorkerLoop:
    def test_closes_and_clears(self) -> None:
        loop = worker_loop.get_worker_loop()
        assert not loop.is_closed()
        worker_loop.reset_worker_loop()
        assert loop.is_closed()
        assert worker_loop._worker_loop is None

    def test_noop_when_none(self) -> None:
        worker_loop._worker_loop = None
        worker_loop.reset_worker_loop()  # should not raise
