from functools import partial
from threading import Event, get_ident
from types import SimpleNamespace

import anyio
import pytest
from creator_service.task_dispatch_service import TaskDispatchService
from httpx import ASGITransport, AsyncClient
from shorts_api.main import app
from shorts_api.task_dispatch_adapter import ApplicationTaskDispatcher


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [True, False])
async def test_health_completes_during_actual_dispatch(monkeypatch, queued):
    # Given an actual adapter with a synchronous broker/task rendezvous.
    adapter = ApplicationTaskDispatcher()
    service = TaskDispatchService(adapter)
    entered, release = Event(), Event()
    observed, results = [], []
    loop_thread = get_ident()
    if queued:
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1")
    else:
        monkeypatch.delenv("REDIS_URL", raising=False)

    def blocked(*args, **kwargs):
        observed.append(get_ident())
        entered.set()
        assert release.wait(5), "dispatch blocked the request loop"
        return SimpleNamespace(id=kwargs.get("task_id", "queued"))

    monkeypatch.setattr(adapter, "_load_task", lambda _: SimpleNamespace(run=blocked, apply_async=blocked))
    monkeypatch.setattr(adapter, "_get_trace_headers", lambda: {})
    storage = SimpleNamespace(conditional_update_run=None)

    async def update(*args, **kwargs):
        return True, {"current_stage": "RENDER_GENERATING"}

    async def get_run(*args, **kwargs):
        return SimpleNamespace(project_id=1, status="running")

    storage.conditional_update_run = update

    async def dispatch():
        results.append(await service.cas_dispatch_with_rollback(
            run_id=1, expected_stages=frozenset({"SUBTITLE_GENERATING"}),
            target_stage="RENDER_GENERATING", dispatcher=partial(service.dispatch_render_video, 1, "vertical"),
            dispatcher_args={}, run_service=SimpleNamespace(storage=storage, get_run=get_run),
            rollback_stage="SUBTITLE_GENERATING", rollback_restart_from=None, enqueue_error_detail="unavailable",
        ))

    # When dispatch is blocked, concurrent health must finish before release.
    async with anyio.create_task_group() as group:
        group.start_soon(dispatch)
        try:
            assert await anyio.to_thread.run_sync(entered.wait, 5)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                with anyio.fail_after(5):
                    assert (await client.get("/healthz")).status_code == 200
            assert not results
            assert observed[0] != loop_thread
        finally:
            release.set()
    # Then dispatch returns the actual task identity only after completion.
    assert results[0]["task_id"] == "queued" if queued else results[0]["task_id"].startswith("sync-")
