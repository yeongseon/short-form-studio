from threading import Event, Lock

import anyio
import pytest
from creator_service.blocking_io import run_blocking, run_control


@pytest.mark.asyncio
async def test_offload_bounds_running_work_and_keeps_cancelled_work_owned():
    entered, release = Event(), Event()
    lock = Lock()
    active = 0
    peak = 0
    finished = 0
    scope = anyio.CancelScope()

    def blocked():
        nonlocal active, peak, finished
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 8:
                entered.set()
        assert release.wait(5)
        with lock:
            active -= 1
            finished += 1

    async def requests():
        with scope:
            async with anyio.create_task_group() as group:
                for _ in range(12):
                    group.start_soon(run_blocking, blocked)

    async with anyio.create_task_group() as group:
        group.start_soon(requests)
        try:
            assert await anyio.to_thread.run_sync(entered.wait, 5)
            with anyio.fail_after(5):
                assert await run_control(lambda: "revoked") == "revoked"
            scope.cancel()
            await anyio.lowlevel.checkpoint()
            assert active == 8 and finished == 0
        finally:
            release.set()
    assert peak == 8
    assert finished == 8
