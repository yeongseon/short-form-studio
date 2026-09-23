import sys
from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import pytest
from shorts_api.routes import creator_runs_utils, storyboard_dispatch


@pytest.mark.asyncio
@pytest.mark.parametrize("storyboard", [True, False])
async def test_revoke_is_completed_off_loop_before_tracking(monkeypatch, storyboard):
    entered, release = Event(), Event()
    loop_thread = get_ident()
    threads = []
    marks = AsyncMock()

    def revoke(*args, **kwargs):
        threads.append(get_ident())
        entered.set()
        assert release.wait(5)

    monkeypatch.setitem(sys.modules, "celery_app", SimpleNamespace(celery_app=SimpleNamespace(control=SimpleNamespace(revoke=revoke))))
    monkeypatch.setattr(storyboard_dispatch.task_dispatch_service.dispatcher, "cancel", revoke)
    monkeypatch.setattr(storyboard_dispatch.task_tracking_service, "mark_tasks_revoked", marks)

    async def request():
        if storyboard:
            await storyboard_dispatch._revoke_and_mark("task-1")
        else:
            assert await creator_runs_utils._revoke_celery_ids(["task-1"], 1)

    async with anyio.create_task_group() as group:
        group.start_soon(request)
        try:
            assert await anyio.to_thread.run_sync(entered.wait, 5)
            marks.assert_not_awaited()
            assert threads[0] != loop_thread
        finally:
            release.set()
    marks.assert_awaited_once_with(["task-1"])
