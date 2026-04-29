import asyncio
from datetime import datetime, timedelta, timezone

from creator_service.task_tracking_service import InMemoryTaskTrackingStorage, TaskTrackingService


def test_record_task_start_creates_pending_task() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())
    task = asyncio.run(service.record_task_start(7, "generate_script", "celery-1"))
    assert task.run_id == 7
    assert task.task_type == "generate_script"
    assert task.status == "pending"


def test_mark_running_updates_status_and_started_at() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())
    asyncio.run(service.record_task_start(7, "generate_script", "celery-1"))
    task = asyncio.run(service.mark_running("celery-1"))
    assert task is not None
    assert task.status == "running"
    assert task.started_at is not None


def test_mark_success_updates_status_and_finished_at() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())
    asyncio.run(service.record_task_start(7, "generate_script", "celery-1"))
    task = asyncio.run(service.mark_success("celery-1"))
    assert task is not None
    assert task.status == "success"
    assert task.finished_at is not None


def test_mark_failed_records_error_info() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())
    asyncio.run(service.record_task_start(7, "generate_script", "celery-1"))
    task = asyncio.run(service.mark_failed("celery-1", "RuntimeError", "boom"))
    assert task is not None
    assert task.status == "failed"
    assert task.error_code == "RuntimeError"
    assert task.error_message == "boom"


def test_list_run_tasks_returns_newest_first() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())
    asyncio.run(service.record_task_start(9, "generate_script", "celery-1"))
    asyncio.run(service.record_task_start(9, "generate_audio", "celery-2"))
    tasks = asyncio.run(service.list_run_tasks(9))
    assert [task.celery_task_id for task in tasks] == ["celery-2", "celery-1"]


def test_find_stuck_tasks_returns_only_stuck_tasks() -> None:
    storage = InMemoryTaskTrackingStorage()
    service = TaskTrackingService(storage)
    old_task = asyncio.run(service.record_task_start(9, "generate_script", "celery-old"))
    fresh_task = asyncio.run(service.record_task_start(9, "generate_script", "celery-fresh"))
    asyncio.run(service.mark_running("celery-old"))
    asyncio.run(service.mark_running("celery-fresh"))

    old_row = storage._rows[old_task.id]
    old_row["started_at"] = datetime.now(timezone.utc) - timedelta(seconds=120)
    storage._rows[old_task.id] = old_row

    fresh_row = storage._rows[fresh_task.id]
    fresh_row["started_at"] = datetime.now(timezone.utc)
    storage._rows[fresh_task.id] = fresh_row

    stuck = asyncio.run(service.find_stuck_tasks(threshold_seconds=60))
    assert [task.celery_task_id for task in stuck] == ["celery-old"]


def test_record_task_start_reuses_celery_task_id_and_increments_attempt() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())
    first = asyncio.run(service.record_task_start(7, "generate_script", "celery-retry-1"))
    retried = asyncio.run(service.record_task_start(7, "generate_script", "celery-retry-1"))

    assert retried.id == first.id
    assert retried.attempt == 2
    assert retried.status == "running"
    assert retried.started_at is not None


def test_mark_rejected_transitions_running_to_rejected() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())
    asyncio.run(service.record_task_start(7, "generate_script", "celery-rej-1"))
    asyncio.run(service.mark_running("celery-rej-1"))
    result = asyncio.run(service.mark_rejected("celery-rej-1", "stage_guard"))
    assert result is not None
    assert result.status == "rejected"
    assert result.finished_at is not None
