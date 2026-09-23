from types import SimpleNamespace
import pytest
from creator_domain.task_dispatch import SynchronousTaskExecutionError, TaskSubmission
from creator_service.blocking_io import run_blocking
from shorts_api.task_dispatch_adapter import ApplicationTaskDispatcher


@pytest.mark.asyncio
async def test_lightweight_failure_does_not_overwrite_concurrently_cancelled_run(monkeypatch):
    from creator_service.run_service import run_service

    row = {"status": "cancelled", "current_stage": "RENDER_GENERATING"}

    async def update(run_id, updates):
        row.update(updates)

    async def conditional(run_id, updates, *, expected_stages, **kwargs):
        if row["status"] in kwargs.get("rejected_statuses", ()):
            return False, row
        row.update(updates)
        return True, row

    monkeypatch.setattr(run_service, "storage", SimpleNamespace(update_run=update, conditional_update_run=conditional))
    monkeypatch.delenv("REDIS_URL", raising=False)
    adapter = ApplicationTaskDispatcher()

    def fail(*args, **kwargs):
        raise RuntimeError("provider failure after cancellation")

    monkeypatch.setattr(adapter, "_load_task", lambda _: SimpleNamespace(run=fail))
    with pytest.raises(SynchronousTaskExecutionError):
        await run_blocking(lambda: adapter.dispatch(TaskSubmission("render_video", 1)))
    assert row["status"] == "cancelled"
