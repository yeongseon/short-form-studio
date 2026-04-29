import asyncio

from creator_service.task_tracking_service import InMemoryTaskTrackingStorage, TaskTrackingService


def test_attempt_increments_only_on_retry_requeue() -> None:
    service = TaskTrackingService(InMemoryTaskTrackingStorage())

    queued = asyncio.run(service.record_task_queued(42, "generate_script", "celery-attempt-1"))
    assert queued.attempt == 1
    assert queued.status == "queued"

    first_running = asyncio.run(
        service.record_task_start(42, "generate_script", "celery-attempt-1")
    )
    assert first_running.attempt == 1
    assert first_running.status == "running"

    failed = asyncio.run(service.mark_failed("celery-attempt-1", "RuntimeError", "boom"))
    assert failed is not None
    assert failed.status == "failed"

    retried_queued = asyncio.run(
        service.record_task_queued(42, "generate_script", "celery-attempt-1")
    )
    assert retried_queued.attempt == 2
    assert retried_queued.status == "queued"

    second_running = asyncio.run(
        service.record_task_start(42, "generate_script", "celery-attempt-1")
    )
    assert second_running.attempt == 2
    assert second_running.status == "running"
