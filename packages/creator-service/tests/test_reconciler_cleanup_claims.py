from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from creator_service.dispatch_reconciler import DispatchReconciler
from creator_service.memory_task_tracking_storage import InMemoryTaskTrackingStorage
from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage
from creator_service.postgres_usage_storage import PostgresUsageStorage
from creator_service.task_tracking_service import TaskTrackingService
from creator_service.usage_service import InMemoryUsageStorage, UsageService

from .quota_dispatch_support import quota_pool as quota_pool


class CleanupDiscoveryBarrier(TaskTrackingService):
    def __init__(
        self,
        storage: InMemoryTaskTrackingStorage | PostgresTaskTrackingStorage,
    ) -> None:
        super().__init__(storage)
        self.discovered = asyncio.Event()
        self.resume = asyncio.Event()

    async def find_reconciliation_pending_tasks(
        self, lease_seconds: int = 300
    ):
        tasks = await super().find_reconciliation_pending_tasks(lease_seconds)
        self.discovered.set()
        await self.resume.wait()
        return tasks


class CleanupTakeoverBarrier(TaskTrackingService):
    def __init__(
        self,
        storage: InMemoryTaskTrackingStorage | PostgresTaskTrackingStorage,
    ) -> None:
        super().__init__(storage)
        self.claimed = asyncio.Event()
        self.resume = asyncio.Event()
        self.finalizations = 0

    async def claim_reconciliation(
        self, task_id: int, claim_token: str, lease_seconds: int = 300
    ):
        task = await super().claim_reconciliation(task_id, claim_token, lease_seconds)
        if task is not None:
            self.claimed.set()
            await self.resume.wait()
        return task

    async def finish_reconciliation(
        self,
        celery_task_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
    ):
        task = await super().finish_reconciliation(
            celery_task_id, claim_token, error_code, error_message
        )
        if task is not None:
            self.finalizations += 1
        return task


async def _failed_enqueue(celery_task_id: str, task_type: str, run_id: int) -> bool:
    return False


async def _prepare_run(pool: asyncpg.Pool | None) -> int:
    if pool is None:
        return 1
    project_id = await pool.fetchval(
        "INSERT INTO creator_projects (workspace_id) VALUES (1) RETURNING id"
    )
    return await pool.fetchval(
        """INSERT INTO creator_runs
           (project_id, workspace_id, current_stage, status, style_preset)
           VALUES ($1, 1, 'AUDIO_GENERATING', 'pending', 'default') RETURNING id""",
        project_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_broker_epoch_witness_survives_recovery_process_state_loss(
    quota_pool: asyncpg.Pool | None,
) -> None:
    # Given: the recovery process records a broker generation in durable tracking storage.
    first_storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    await first_storage.set_observed_broker_epoch("epoch-a")
    second_storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else first_storage
    )

    # When
    observed = await second_storage.get_observed_broker_epoch()

    # Then
    assert observed == "epoch-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_first_broker_observation_adopts_legacy_active_tasks_atomically(
    quota_pool: asyncpg.Pool | None,
) -> None:
    # Given legacy NULL-generation rows in every active state and one completed row.
    storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    tracking = TaskTrackingService(storage)
    run_id = await _prepare_run(quota_pool)
    for status in ("pending", "queued", "running", "success"):
        await storage.create_task(
            {
                "run_id": run_id,
                "task_type": "generate_audio",
                "celery_task_id": f"legacy-{status}",
                "status": status,
                "attempt": 1,
            }
        )

    # When the process establishes its first durable broker observation.
    await tracking.set_observed_broker_epoch("epoch-a")

    # Then all active legacy rows belong to that generation; success stays unowned.
    tasks = {task.status: task for task in await tracking.list_run_tasks(run_id)}
    assert tasks["pending"].broker_generation == "epoch-a"
    assert tasks["queued"].broker_generation == "epoch-a"
    assert tasks["running"].broker_generation == "epoch-a"
    assert tasks["success"].broker_generation is None
    assert await tracking.get_observed_broker_epoch() == "epoch-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["postgres"], indirect=True)
async def test_concurrent_first_broker_observers_adopt_one_generation(
    quota_pool: asyncpg.Pool | None,
) -> None:
    # Given PostgreSQL legacy rows and two simultaneous first observations.
    assert quota_pool is not None
    storage = PostgresTaskTrackingStorage()
    run_id = await _prepare_run(quota_pool)
    for status in ("pending", "queued", "running", "success"):
        await storage.create_task(
            {
                "run_id": run_id,
                "task_type": "generate_audio",
                "celery_task_id": f"concurrent-legacy-{status}",
                "status": status,
                "attempt": 1,
            }
        )

    # When both observers race to establish different current epochs.
    await asyncio.gather(
        storage.set_observed_broker_epoch("epoch-a"),
        storage.set_observed_broker_epoch("epoch-b"),
    )

    # Then every active row adopts the same winning first epoch and success stays NULL.
    rows = await storage.list_by_run(run_id)
    active_generations = {
        row["broker_generation"]
        for row in rows
        if row["status"] in ("pending", "queued", "running")
    }
    success = next(row for row in rows if row["status"] == "success")
    assert active_generations in ({"epoch-a"}, {"epoch-b"})
    assert success["broker_generation"] is None
    assert await storage.get_observed_broker_epoch() in {"epoch-a", "epoch-b"}


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_cleanup_marker_cannot_be_reclaimed_by_worker_or_dispatch(
    quota_pool: asyncpg.Pool | None,
) -> None:
    storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    tracking = TaskTrackingService(storage)
    run_id = await _prepare_run(quota_pool)
    await tracking.record_task_pending(run_id, "generate_audio", "attempt-a")
    await tracking.mark_failed_if_pending(
        "attempt-a", "reconciler_pending_cleanup", "cleanup"
    )

    worker_claim = await tracking.record_task_start(
        run_id, "generate_audio", "attempt-a", claim_token="worker"
    )
    with pytest.raises(ValueError, match="Failed to record pending task"):
        await tracking.record_task_pending(run_id, "generate_audio", "attempt-a")

    task = await storage.get_by_celery_id("attempt-a")
    assert worker_claim is None
    assert task is not None and task["error_code"] == "reconciler_pending_cleanup"


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_broker_recovery_marker_cannot_be_reclaimed_by_worker_or_dispatch(
    quota_pool: asyncpg.Pool | None,
) -> None:
    # Given: broker recovery has fenced an active attempt for cleanup.
    storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    tracking = TaskTrackingService(storage)
    run_id = await _prepare_run(quota_pool)
    await tracking.record_task_pending(run_id, "generate_audio", "attempt-a")
    marked = await tracking.mark_failed_if_active(
        "attempt-a", "broker_recovery_cleanup", "cleanup"
    )
    assert marked is not None

    # When: a late worker delivery and a duplicate dispatch try to reclaim it.
    worker_claim = await tracking.record_task_start(
        run_id, "generate_audio", "attempt-a", claim_token="worker"
    )

    # Then: neither path can overwrite the recovery cleanup marker.
    assert worker_claim is None
    with pytest.raises(ValueError, match="Failed to record pending task"):
        await tracking.record_task_pending(run_id, "generate_audio", "attempt-a")
    task = await storage.get_by_celery_id("attempt-a")
    assert task is not None and task["error_code"] == "broker_recovery_cleanup"


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_two_reconcilers_claim_discovered_cleanup_once(
    monkeypatch: pytest.MonkeyPatch,
    quota_pool: asyncpg.Pool | None,
) -> None:
    storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    tracking = TaskTrackingService(storage)
    run_id = await _prepare_run(quota_pool)
    await tracking.record_task_pending(run_id, "generate_audio", "attempt-a")
    await tracking.mark_failed_if_pending(
        "attempt-a", "reconciler_pending_cleanup", "cleanup"
    )
    first_tracking = CleanupDiscoveryBarrier(storage)
    second_tracking = CleanupDiscoveryBarrier(storage)
    rollbacks: list[str] = []

    async def rollback(run_id: int, task_id: str) -> None:
        rollbacks.append(task_id)

    async def cancel_owned(task_id: str) -> bool:
        return True

    monkeypatch.setattr(
        "creator_service.usage_service.usage_service.cancel_owned", cancel_owned
    )
    first = asyncio.create_task(
        DispatchReconciler(
            task_tracking_service=first_tracking,
            enqueue_fn=_failed_enqueue,
            rollback_fn=rollback,
        ).reconcile()
    )
    second = asyncio.create_task(
        DispatchReconciler(
            task_tracking_service=second_tracking,
            enqueue_fn=_failed_enqueue,
            rollback_fn=rollback,
        ).reconcile()
    )
    await asyncio.gather(
        first_tracking.discovered.wait(), second_tracking.discovered.wait()
    )
    first_tracking.resume.set()
    second_tracking.resume.set()

    results = await asyncio.gather(first, second)

    assert rollbacks == ["attempt-a"]
    assert sum(result.rolled_back for result in results) == 1


@pytest.mark.asyncio
async def test_quota_cancellation_failure_keeps_cleanup_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = InMemoryTaskTrackingStorage()
    tracking = TaskTrackingService(storage)
    await tracking.record_task_pending(1, "generate_audio", "attempt-a")
    cancellations = 0

    async def cancel_owned(task_id: str) -> bool:
        nonlocal cancellations
        cancellations += 1
        if cancellations == 1:
            raise OSError("injected quota cancellation failure")
        return True

    async def rollback(run_id: int, task_id: str) -> None:
        return None

    monkeypatch.setattr(
        "creator_service.usage_service.usage_service.cancel_owned", cancel_owned
    )
    reconciler = DispatchReconciler(
        task_tracking_service=tracking,
        enqueue_fn=_failed_enqueue,
        rollback_fn=rollback,
        threshold_seconds=-1,
    )

    first = await reconciler.reconcile()
    retryable = await storage.get_by_celery_id("attempt-a")
    second = await reconciler.reconcile()

    assert first.errors
    assert retryable is not None
    assert retryable["error_code"] == "reconciler_pending_cleanup"
    assert second.rolled_back == 1
    assert cancellations == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_expired_cleanup_claim_is_taken_over_and_finalized_once(
    monkeypatch: pytest.MonkeyPatch,
    quota_pool: asyncpg.Pool | None,
) -> None:
    storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    tracking = TaskTrackingService(storage)
    run_id = await _prepare_run(quota_pool)
    await tracking.record_task_pending(run_id, "generate_audio", "attempt-a")
    marked = await tracking.mark_failed_if_pending(
        "attempt-a", "reconciler_pending_cleanup", "cleanup"
    )
    assert marked is not None
    abandoned_token = "owner-died"
    claimed = await tracking.claim_reconciliation(marked.id, abandoned_token)
    assert claimed is not None
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=301)
    if quota_pool is None:
        storage._rows[marked.id]["finished_at"] = expired_at
    else:
        await quota_pool.execute(
            "UPDATE creator_run_tasks SET finished_at=$1 WHERE id=$2",
            expired_at,
            marked.id,
        )
    usage = UsageService(
        PostgresUsageStorage() if quota_pool is not None else InMemoryUsageStorage()
    )
    await usage.set_quota(1, monthly_tts_requests=1)
    assert await usage.reserve_owned(1, "tts", "attempt-a")
    cancellations = 0
    cancel_owned = usage.cancel_owned

    async def count_cancel_owned(task_id: str) -> bool:
        nonlocal cancellations
        cancellations += 1
        return await cancel_owned(task_id)

    monkeypatch.setattr(usage, "cancel_owned", count_cancel_owned)
    monkeypatch.setattr("creator_service.usage_service.usage_service", usage)
    takeover = CleanupTakeoverBarrier(storage)
    rollbacks: list[str] = []

    async def rollback(run_id: int, task_id: str) -> None:
        rollbacks.append(task_id)

    second_owner = asyncio.create_task(
        DispatchReconciler(
            task_tracking_service=takeover,
            enqueue_fn=_failed_enqueue,
            rollback_fn=rollback,
        ).reconcile()
    )
    await asyncio.wait_for(takeover.claimed.wait(), timeout=1)

    stale_finish = await tracking.finish_reconciliation(
        "attempt-a", abandoned_token, "reconciler_rollback", "stale owner"
    )
    takeover.resume.set()
    recovered = await second_owner
    repeated = await DispatchReconciler(
        task_tracking_service=tracking,
        enqueue_fn=_failed_enqueue,
        rollback_fn=rollback,
    ).reconcile()

    task = await storage.get_by_celery_id("attempt-a")
    assert stale_finish is None
    assert recovered.rolled_back == 1
    assert repeated.rolled_back == 0
    assert rollbacks == ["attempt-a"]
    assert cancellations == 1
    assert takeover.finalizations == 1
    assert task is not None and task["error_code"] == "reconciler_rollback"
    assert await usage.reserve_owned(1, "tts", "replacement")
