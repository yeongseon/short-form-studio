from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from creator_service.telemetry import get_meter


_METER = get_meter(__name__)
_QUEUE_LENGTH = _METER.create_histogram("worker.queue.length")
_OLDEST_WAIT = _METER.create_histogram("worker.queue.oldest_wait_seconds")
_RECOVERY_FAILURES = _METER.create_counter("worker.queue.recovery_failures")


class RecoverableTask(Protocol):
    celery_task_id: str
    run_id: int
    status: str
    created_at: datetime


class TaskRoute(Protocol):
    def get(self, key: str) -> str | None: ...


class RecoveryTracking(Protocol):
    async def list_broker_recovery_tasks(self) -> list[RecoverableTask]: ...

    async def mark_failed_if_active(
        self, task_id: str, error_code: str, error_message: str
    ) -> RecoverableTask | None: ...

    async def mark_failed(
        self, task_id: str, error_code: str, error_message: str
    ) -> RecoverableTask | None: ...


class OwnedUsage(Protocol):
    async def cancel_owned(self, task_id: str) -> bool: ...


def routed_queue_names(
    *, default_queue: str, routes: Mapping[str, TaskRoute]
) -> tuple[str, ...]:
    queues = {default_queue}
    queues.update(
        queue
        for route in routes.values()
        if (queue := route.get("queue")) is not None
    )
    return tuple(sorted(queues))


def oldest_active_wait_seconds(
    tasks: list[RecoverableTask], *, now: datetime
) -> float | None:
    waiting = [
        (now - task.created_at).total_seconds()
        for task in tasks
        if task.status in {"pending", "queued"}
    ]
    return max(waiting) if waiting else None


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    epoch: str
    started_at: datetime
    queue_length: int
    oldest_wait_seconds: float | None
    workers_online: int


@dataclass(frozen=True, slots=True)
class BrokerRecoveryResult:
    failed: int
    deferred: bool
    queue_length: int
    oldest_wait_seconds: float | None
    recovery_failures: int


async def recover_lost_tasks(
    *,
    previous_epoch: str | None,
    snapshot: BrokerSnapshot,
    tracking: RecoveryTracking,
    usage: OwnedUsage,
    rollback: Callable[[int, str], Awaitable[None]],
) -> BrokerRecoveryResult:
    _QUEUE_LENGTH.record(snapshot.queue_length)
    if snapshot.oldest_wait_seconds is not None:
        _OLDEST_WAIT.record(snapshot.oldest_wait_seconds)
    epoch_replaced = previous_epoch is not None and previous_epoch != snapshot.epoch
    evidence_complete = snapshot.queue_length == 0 and snapshot.workers_online > 0
    if not epoch_replaced:
        return _result(snapshot, failed=0, deferred=False, recovery_failures=0)
    if not evidence_complete:
        return _result(snapshot, failed=0, deferred=True, recovery_failures=0)

    failed = 0
    recovery_failures = 0
    for task in await tracking.list_broker_recovery_tasks():
        if task.created_at >= snapshot.started_at:
            continue
        marked = await tracking.mark_failed_if_active(
            task.celery_task_id,
            error_code="broker_recovery_cleanup",
            error_message="Broker replacement recovery requires compensation",
        )
        if marked is None:
            continue
        try:
            await rollback(task.run_id, task.celery_task_id)
            await usage.cancel_owned(task.celery_task_id)
        except Exception:  # noqa: BLE001 - compensation must continue for other owners
            recovery_failures += 1
            continue
        await tracking.mark_failed(
            task.celery_task_id,
            error_code="broker_message_lost",
            error_message="Broker storage was replaced; use manual retry",
        )
        failed += 1
    _RECOVERY_FAILURES.add(recovery_failures)
    return _result(
        snapshot,
        failed=failed,
        deferred=False,
        recovery_failures=recovery_failures,
    )


def _result(
    snapshot: BrokerSnapshot,
    *,
    failed: int,
    deferred: bool,
    recovery_failures: int,
) -> BrokerRecoveryResult:
    return BrokerRecoveryResult(
        failed=failed,
        deferred=deferred,
        queue_length=snapshot.queue_length,
        oldest_wait_seconds=snapshot.oldest_wait_seconds,
        recovery_failures=recovery_failures,
    )


def should_persist_observed_epoch(*, previous_epoch: str | None, deferred: bool) -> bool:
    return previous_epoch is None or not deferred
