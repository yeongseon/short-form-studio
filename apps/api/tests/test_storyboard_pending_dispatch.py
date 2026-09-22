from collections.abc import Callable
from types import SimpleNamespace
from uuid import UUID

import pytest
from creator_domain.models.run_task import RunTask
from creator_service.task_tracking_service import InMemoryTaskTrackingStorage, TaskTrackingService
from fastapi import HTTPException

from shorts_api.routes import storyboard_dispatch as dispatch_module


class Tracking(TaskTrackingService):
    def __init__(self) -> None:
        super().__init__(InMemoryTaskTrackingStorage())
        self.events: list[tuple[str, str]] = []
        self.fail_pending = False
        self.fail_promotion = False
        self.pending_attempts = 0
        self.before_promotion: str | None = None

    async def record_task_pending(self, run_id: int, task_type: str, celery_task_id: str) -> RunTask:
        self.pending_attempts += 1
        if self.fail_pending:
            raise RuntimeError("pending unavailable")
        task = await super().record_task_pending(run_id, task_type, celery_task_id)
        self.events.append(("pending", celery_task_id))
        return task

    async def promote_pending_to_queued(self, celery_task_id: str) -> RunTask | None:
        self.events.append(("promote", celery_task_id))
        if self.before_promotion is not None:
            row = await self.storage.get_by_celery_id(celery_task_id)
            assert row is not None
            await self.storage.update_task_status(row["id"], self.before_promotion)
        if self.fail_promotion:
            raise RuntimeError("promotion unavailable")
        return await super().promote_pending_to_queued(celery_task_id)


class Cancellation:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    def cancel(self, task_id: str) -> None:
        self.calls.append(task_id)
        if self.fail:
            raise RuntimeError("broker unavailable")


@pytest.fixture
def boundary(monkeypatch: pytest.MonkeyPatch):
    tracking = Tracking()
    cancellation = Cancellation()
    quota: list[tuple[int, str]] = []

    async def fresh_run(run_id: int, workspace_id: int):
        return SimpleNamespace(status="running")

    async def release(workspace_id: int, operation_type: str) -> None:
        quota.append((workspace_id, operation_type))

    async def reserve(workspace_id: int, operation_type: str) -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr(dispatch_module, "task_tracking_service", tracking)
    monkeypatch.setattr(dispatch_module, "_get_fresh_run_for_dispatch", fresh_run)
    monkeypatch.setattr(dispatch_module, "cancel_workspace_quota_reservation", release)
    monkeypatch.setattr("creator_service.usage_service.check_workspace_quota", reserve)
    monkeypatch.setattr("creator_service.task_dispatch_service.task_dispatch_service.dispatcher.cancel", cancellation.cancel)
    return tracking, cancellation, quota


async def invoke(bulk: bool, dispatch: Callable[[str], str]):
    if bulk:
        return await dispatch_module.dispatch_storyboard_task_bulk(
            run_id=4, workspace_id=8, operation_type="tts", task_type="generate_paragraph_audio",
            section_id="section-1", dispatch=dispatch,
        )
    return await dispatch_module.dispatch_storyboard_task_with_tracking(
        run_id=4, workspace_id=8, operation_type="tts", task_type="generate_paragraph_audio",
        dispatch=dispatch,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
async def test_pending_is_durable_before_publish_and_same_uuid_is_promoted(boundary, bulk: bool) -> None:
    tracking, cancellation, quota = boundary

    def publish(task_id: str) -> str:
        assert UUID(task_id).version == 4
        assert tracking.events == [("pending", task_id)]
        tracking.events.append(("publish", task_id))
        return task_id

    result = await invoke(bulk, publish)

    task_id = result["task_id"] if bulk else result
    assert tracking.events == [("pending", task_id), ("publish", task_id), ("promote", task_id)]
    tasks = await tracking.list_run_tasks(4)
    assert [(task.celery_task_id, task.status) for task in tasks] == [(task_id, "queued")]
    assert cancellation.calls == []
    assert quota == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("phase", ["pending", "publish", "promote"])
@pytest.mark.parametrize("revoke_fails", [False, True])
async def test_failure_compensates_tracking_and_quota_even_when_revoke_fails(boundary, bulk: bool, phase: str, revoke_fails: bool) -> None:
    tracking, cancellation, quota = boundary
    tracking.fail_pending = phase == "pending"
    tracking.fail_promotion = phase == "promote"
    cancellation.fail = revoke_fails
    published: list[str] = []

    def publish(task_id: str) -> str:
        published.append(task_id)
        if phase == "publish":
            raise RuntimeError("broker accepted but acknowledgement lost")
        return task_id

    if bulk:
        result = await invoke(bulk, publish)
        assert result == {"section_id": "section-1", "task_id": "", "error": "dispatch_failed"}
    else:
        with pytest.raises(HTTPException) as error:
            await invoke(bulk, publish)
        assert error.value.status_code == 503

    assert quota == [(8, "tts")]
    assert tracking.pending_attempts == 1
    tasks = await tracking.list_run_tasks(4)
    if phase == "pending":
        assert published == []
        assert tasks == []
        assert cancellation.calls == []
    else:
        assert len(published) == 1
        assert cancellation.calls == published
        assert [(task.celery_task_id, task.status) for task in tasks] == [(published[0], "revoked")]


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("status", ["running", "success", "failed", "revoked", "rejected"])
async def test_promotion_preserves_concurrent_worker_or_cancel_state(boundary, bulk: bool, status: str) -> None:
    tracking, cancellation, quota = boundary
    tracking.before_promotion = status

    result = await invoke(bulk, lambda task_id: task_id)

    task_id = result["task_id"] if bulk else result
    tasks = await tracking.list_run_tasks(4)
    assert [(task.celery_task_id, task.status) for task in tasks] == [(task_id, status)]
    assert cancellation.calls == []
    assert quota == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
async def test_promotion_failure_does_not_overwrite_completed_task(boundary, bulk: bool) -> None:
    tracking, cancellation, quota = boundary
    tracking.before_promotion = "success"
    tracking.fail_promotion = True

    if bulk:
        result = await invoke(bulk, lambda task_id: task_id)
        assert result["error"] == "dispatch_failed"
    else:
        with pytest.raises(HTTPException) as error:
            await invoke(bulk, lambda task_id: task_id)
        assert error.value.status_code == 503

    tasks = await tracking.list_run_tasks(4)
    assert len(tasks) == 1
    assert tasks[0].status == "success"
    assert cancellation.calls == [tasks[0].celery_task_id]
    assert quota == [(8, "tts")]


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
async def test_post_publish_cancellation_revokes_preregistered_task(boundary, monkeypatch: pytest.MonkeyPatch, bulk: bool) -> None:
    tracking, cancellation, quota = boundary
    states = iter(("running", "cancelled"))

    async def fresh_run(run_id: int, workspace_id: int):
        return SimpleNamespace(status=next(states))

    monkeypatch.setattr(dispatch_module, "_get_fresh_run_for_dispatch", fresh_run)
    with pytest.raises(HTTPException) as error:
        await invoke(bulk, lambda task_id: task_id)

    assert error.value.status_code == 409
    tasks = await tracking.list_run_tasks(4)
    assert len(tasks) == 1
    assert tasks[0].status == "revoked"
    assert cancellation.calls == [tasks[0].celery_task_id]
    assert quota == [(8, "tts")]
