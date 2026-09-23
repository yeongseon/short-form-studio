from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import pytest
from creator_service.task_dispatch_service import TaskDispatchService
from shorts_api.task_dispatch_adapter import ApplicationTaskDispatcher


@pytest.mark.asyncio
async def test_cancel_during_publish_waits_then_revokes_before_releasing_quota(monkeypatch):
    from creator_service import dispatch_cas, dispatch_quota, task_tracking_service

    entered, release = Event(), Event()
    scope = anyio.CancelScope()
    events = []
    adapter = ApplicationTaskDispatcher()
    service = TaskDispatchService(adapter)
    monkeypatch.setenv("REDIS_URL", "redis://unused")
    monkeypatch.setattr(adapter, "_get_trace_headers", lambda: {})
    run = SimpleNamespace(status="running", project_id=1)

    async def pending(*args):
        events.append("pending")

    def publish(**kwargs):
        assert events == ["reserve", "stage", "pending"]
        entered.set()
        assert release.wait(5)
        events.append("published")
        return SimpleNamespace(id=kwargs["task_id"])

    async def reserve(*args, **kwargs):
        events.append("reserve")
        return 1

    async def compensate(*args, **kwargs):
        events.append("released")

    async def stage(*args, **kwargs):
        events.append("stage")
        return True, {}

    async def fresh(*args, **kwargs):
        await anyio.lowlevel.checkpoint()
        return run

    monkeypatch.setattr(dispatch_cas, "reserve_quota", reserve)
    monkeypatch.setattr(dispatch_cas, "cancel_quota", compensate)
    monkeypatch.setattr(dispatch_quota, "cancel_quota", compensate)
    monkeypatch.setattr(adapter, "_load_task", lambda _: SimpleNamespace(apply_async=publish))
    monkeypatch.setattr(adapter, "cancel", lambda _: events.append("revoked"))
    tracking = task_tracking_service.task_tracking_service
    monkeypatch.setattr(tracking, "record_task_pending", pending)
    monkeypatch.setattr(tracking, "promote_pending_to_queued", AsyncMock())
    monkeypatch.setattr(tracking, "mark_tasks_revoked", AsyncMock())
    errors = []

    async def request():
        from creator_domain.exceptions import ConflictError

        with scope:
            try:
                await service.cas_dispatch_with_rollback(
                    run_id=1, expected_stages=frozenset({"SUBTITLE_GENERATING"}), target_stage="RENDER_GENERATING",
                    dispatcher=service.dispatch_render_video, dispatcher_args={"run_id": 1, "render_profile": "vertical"},
                    run_service=SimpleNamespace(get_run=fresh, storage=SimpleNamespace(conditional_update_run=stage)),
                    rollback_stage="SUBTITLE_GENERATING", rollback_restart_from=None, enqueue_error_detail="error",
                    quota_operation_type="render", workspace_id=1,
                )
            except ConflictError:
                errors.append("cancelled run")

    async with anyio.create_task_group() as group:
        group.start_soon(request)
        try:
            assert await anyio.to_thread.run_sync(entered.wait, 5)
            run.status = "cancelled"
            scope.cancel()
            await anyio.lowlevel.checkpoint()
            assert "released" not in events and "published" not in events
        finally:
            release.set()
    assert errors == ["cancelled run"]
    assert events == ["reserve", "stage", "pending", "published", "revoked", "stage", "released"]
