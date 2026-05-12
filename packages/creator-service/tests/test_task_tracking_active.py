import pytest

from creator_service.task_tracking_service import InMemoryTaskTrackingStorage, TaskTrackingService


async def _seed(service: TaskTrackingService) -> None:
    await service.record_task_queued(1, "generate_script", "t-queued")
    await service.record_task_start(1, "generate_script", "t-running")
    await service.record_task_queued(1, "generate_audio", "t-success")
    await service.mark_success("t-success")
    await service.record_task_queued(2, "generate_script", "t-other-run")


@pytest.mark.asyncio
async def test_get_active_celery_ids_filters_by_status_and_run() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())
    await _seed(service)

    ids = await service.get_active_celery_ids(1)

    assert sorted(ids) == ["t-queued", "t-running"]


@pytest.mark.asyncio
async def test_has_active_tasks_true_and_false() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())
    await _seed(service)

    assert await service.has_active_tasks(1) is True
    assert await service.has_active_tasks(999) is False


@pytest.mark.asyncio
async def test_revoke_active_tasks_marks_active_as_revoked() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())
    await _seed(service)

    revoked = await service.revoke_active_tasks(1)

    assert sorted(revoked) == ["t-queued", "t-running"]
    assert await service.has_active_tasks(1) is False
