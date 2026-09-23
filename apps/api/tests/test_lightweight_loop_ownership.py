import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Barrier, get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import pytest
from creator_domain.task_dispatch import TaskSubmission
from creator_service import db
from creator_service.blocking_io import run_blocking
from shorts_api.task_dispatch_adapter import ApplicationTaskDispatcher


@pytest.fixture
def worker_runtime(monkeypatch):
    source = Path(__file__).resolve().parents[2] / "worker-orchestrator" / "worker_loop.py"
    spec = spec_from_file_location("worker_loop", source)
    module = module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "worker_loop", module)
    spec.loader.exec_module(module)
    yield module
    module.reset_worker_loop()


@pytest.mark.asyncio
async def test_overlapping_lightweight_jobs_own_and_close_their_loops_and_pools(monkeypatch, worker_runtime):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    rendezvous = Barrier(2, timeout=5)
    pools, loops, threads = [], [], []
    main_thread = get_ident()

    async def create_pool(*args, **kwargs):
        pool = AsyncMock()
        pools.append(pool)
        return pool

    monkeypatch.setattr(db.asyncpg, "create_pool", create_pool)
    api_pool = await db.get_pool()

    def run(*args, **kwargs):
        async def execute():
            loops.append(worker_runtime.get_worker_loop())
            threads.append(get_ident())
            first = await db.get_pool()
            rendezvous.wait()
            assert await db.get_pool() is first
        worker_runtime.run_in_worker_loop(execute())

    adapter = ApplicationTaskDispatcher()
    monkeypatch.setattr(adapter, "_load_task", lambda _: SimpleNamespace(run=run))
    async with anyio.create_task_group() as group:
        for _ in range(2):
            group.start_soon(run_blocking, lambda: adapter.dispatch(TaskSubmission("render_video", 1)))
    assert len(loops) == 2 and loops[0] is not loops[1]
    assert all(loop.is_closed() for loop in loops)
    assert all(thread != main_thread for thread in threads)
    assert await db.get_pool() is api_pool
    api_pool.close.assert_not_awaited()
    for pool in pools[1:]:
        pool.close.assert_awaited_once()
    assert len(pools) == 3
    await db.close_pool()
