from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from creator_service.broker_recovery import (
    BrokerSnapshot,
    recover_lost_tasks,
    should_persist_observed_epoch,
)
from creator_service.memory_task_tracking_storage import InMemoryTaskTrackingStorage
from creator_service.task_tracking_service import TaskTrackingService


@dataclass
class _Task:
    celery_task_id: str
    run_id: int
    status: str
    created_at: datetime


class _Tracking:
    def __init__(self, tasks: list[_Task]) -> None:
        self.tasks = tasks
        self.failures: dict[str, tuple[str, str]] = {}

    async def list_broker_recovery_tasks(self) -> list[_Task]:
        return self.tasks

    async def mark_failed_if_active(
        self, task_id: str, error_code: str, error_message: str
    ) -> _Task | None:
        task = next(item for item in self.tasks if item.celery_task_id == task_id)
        if task.status not in {"pending", "queued", "running"}:
            return None
        task.status = "failed"
        self.failures[task_id] = (error_code, error_message)
        return task

    async def mark_failed(
        self, task_id: str, error_code: str, error_message: str
    ) -> _Task | None:
        task = next(item for item in self.tasks if item.celery_task_id == task_id)
        task.status = "failed"
        self.failures[task_id] = (error_code, error_message)
        return task


class _Usage:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def cancel_owned(self, task_id: str) -> bool:
        self.cancelled.append(task_id)
        return True


@pytest.mark.asyncio
async def test_slow_healthy_backlog_is_not_failed() -> None:
    # Given: work is old, but the broker epoch is unchanged and has a backlog.
    now = datetime.now(timezone.utc)
    tracking = _Tracking([_Task("queued-a", 1, "queued", now - timedelta(hours=1))])
    usage = _Usage()
    rollbacks: list[tuple[int, str]] = []
    snapshot = BrokerSnapshot(
        epoch="epoch-a", started_at=now - timedelta(minutes=30),
        queue_length=12, oldest_wait_seconds=900.0, workers_online=1
    )

    # When
    result = await recover_lost_tasks(
        previous_epoch="epoch-a",
        snapshot=snapshot,
        tracking=tracking,
        usage=usage,
        rollback=lambda run_id, task_id: _append_rollback(rollbacks, run_id, task_id),
    )

    # Then
    assert result.failed == 0
    assert tracking.tasks[0].status == "queued"
    assert usage.cancelled == []
    assert result.queue_length == 12
    assert result.oldest_wait_seconds == 900.0


@pytest.mark.asyncio
async def test_new_empty_broker_fails_unknown_work_and_releases_owned_quota() -> None:
    # Given: a healthy worker sees a different, empty broker epoch.
    now = datetime.now(timezone.utc)
    tracking = _Tracking(
        [
            _Task("pending-a", 1, "pending", now - timedelta(hours=1)),
            _Task("queued-a", 2, "queued", now - timedelta(hours=1)),
            _Task("running-a", 3, "running", now - timedelta(hours=1)),
            _Task("success-a", 4, "success", now - timedelta(hours=1)),
        ]
    )
    usage = _Usage()
    rollbacks: list[tuple[int, str]] = []

    # When
    result = await recover_lost_tasks(
        previous_epoch="epoch-a",
        snapshot=BrokerSnapshot(
            epoch="epoch-b", started_at=now, queue_length=0,
            oldest_wait_seconds=None, workers_online=1
        ),
        tracking=tracking,
        usage=usage,
        rollback=lambda run_id, task_id: _append_rollback(rollbacks, run_id, task_id),
    )

    # Then: unknown arguments are never replayed; active rows converge to explainable failure.
    assert result.failed == 3
    assert usage.cancelled == ["pending-a", "queued-a", "running-a"]
    assert rollbacks == [(1, "pending-a"), (2, "queued-a"), (3, "running-a")]
    assert tracking.tasks[-1].status == "success"
    for task_id in usage.cancelled:
        code, message = tracking.failures[task_id]
        assert code == "broker_message_lost"
        assert "manual retry" in message.lower()


@pytest.mark.asyncio
async def test_epoch_change_waits_for_worker_and_empty_queue_evidence() -> None:
    # Given: the epoch changed, but worker health cannot yet verify an empty live broker.
    now = datetime.now(timezone.utc)
    tracking = _Tracking([_Task("queued-a", 1, "queued", now - timedelta(hours=1))])
    usage = _Usage()

    # When
    result = await recover_lost_tasks(
        previous_epoch="epoch-a",
        snapshot=BrokerSnapshot(
            epoch="epoch-b", started_at=now, queue_length=0,
            oldest_wait_seconds=None, workers_online=0
        ),
        tracking=tracking,
        usage=usage,
        rollback=lambda run_id, task_id: _append_rollback([], run_id, task_id),
    )

    # Then
    assert result.failed == 0
    assert result.deferred is True
    assert tracking.tasks[0].status == "queued"


@pytest.mark.asyncio
async def test_new_attempt_created_after_recovery_epoch_is_preserved() -> None:
    # Given: manual retry created a successor after broker replacement.
    now = datetime.now(timezone.utc)
    tracking = _Tracking(
        [
            _Task("lost-a", 1, "queued", now - timedelta(hours=1)),
            _Task("retry-a", 1, "running", now + timedelta(seconds=1)),
        ]
    )
    usage = _Usage()
    rollbacks: list[tuple[int, str]] = []

    # When
    result = await recover_lost_tasks(
        previous_epoch="epoch-a",
        snapshot=BrokerSnapshot(
            epoch="epoch-b", started_at=now, queue_length=0,
            oldest_wait_seconds=None, workers_online=1
        ),
        tracking=tracking,
        usage=usage,
        rollback=lambda run_id, task_id: _append_rollback(rollbacks, run_id, task_id),
    )

    # Then: recovery cannot cancel quota or files owned by the successor attempt.
    assert result.failed == 1
    assert usage.cancelled == ["lost-a"]
    assert rollbacks == [(1, "lost-a")]
    assert tracking.tasks[1].status == "running"


@pytest.mark.asyncio
async def test_real_tracking_adapter_fences_late_success_after_recovery() -> None:
    # Given
    storage = InMemoryTaskTrackingStorage()
    tracking = TaskTrackingService(storage)
    now = datetime.now(timezone.utc)
    await tracking.record_task_queued(1, "generate_audio", "lost-a")
    usage = _Usage()

    # When
    result = await recover_lost_tasks(
        previous_epoch="epoch-a",
        snapshot=BrokerSnapshot(
            epoch="epoch-b", started_at=now + timedelta(seconds=1),
            queue_length=0, oldest_wait_seconds=None, workers_online=1
        ),
        tracking=tracking,
        usage=usage,
        rollback=lambda run_id, task_id: _append_rollback([], run_id, task_id),
    )
    late_success = await tracking.mark_success_if_running("lost-a")

    # Then
    row = await storage.get_by_celery_id("lost-a")
    assert result.failed == 1
    assert late_success is None
    assert row is not None and row["status"] == "failed"
    assert row["error_code"] == "broker_message_lost"


async def _append_rollback(
    destination: list[tuple[int, str]], run_id: int, task_id: str
) -> None:
    destination.append((run_id, task_id))


def test_deferred_recovery_keeps_previous_epoch_for_retry() -> None:
    # Given / When / Then
    assert not should_persist_observed_epoch(previous_epoch="epoch-a", deferred=True)
    assert should_persist_observed_epoch(previous_epoch="epoch-a", deferred=False)
    assert should_persist_observed_epoch(previous_epoch=None, deferred=True)
