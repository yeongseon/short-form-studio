from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import asyncpg
import pytest

from creator_service.broker_recovery import BrokerSnapshot, recover_broker_snapshot
from creator_service.memory_task_tracking_storage import InMemoryTaskTrackingStorage
from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage
from creator_service.postgres_usage_storage import PostgresUsageStorage
from creator_service.task_tracking_service import TaskTrackingService
from creator_service.usage_service import InMemoryUsageStorage, UsageService

from .quota_dispatch_support import quota_pool as quota_pool


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
async def test_recovery_resumes_after_epoch_persisted_before_cleanup(
    quota_pool: asyncpg.Pool | None,
) -> None:
    # Given recovery persisted A -> B before interruption, leaving queued A work.
    storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    tracking = TaskTrackingService(storage)
    run_id = await _prepare_run(quota_pool)
    assert await tracking.set_observed_broker_epoch("epoch-a", None)
    await tracking.record_task_pending(
        run_id,
        "generate_audio",
        "obsolete-a",
        broker_generation="epoch-a",
    )
    await tracking.promote_pending_to_queued("obsolete-a")
    assert await tracking.set_observed_broker_epoch("epoch-b", "epoch-a")
    assert await tracking.list_pending_broker_cleanup_generations() == ["epoch-a"]
    await tracking.record_task_pending(
        run_id,
        "generate_audio",
        "current-b",
        broker_generation="epoch-b",
    )
    await tracking.promote_pending_to_queued("current-b")

    # When a later pass observes the healthy, empty B broker.
    result, persisted = await recover_broker_snapshot(
        fallback_epoch=None,
        snapshot=BrokerSnapshot(
            epoch="epoch-b",
            started_at=datetime.now(timezone.utc),
            queue_length=0,
            oldest_wait_seconds=0,
            workers_online=1,
        ),
        tracking=tracking,
        usage=UsageService(
            PostgresUsageStorage()
            if quota_pool is not None
            else InMemoryUsageStorage()
        ),
        rollback=lambda _run_id, _task_id: asyncio.sleep(0),
    )

    # Then obsolete A work converges while current B work remains queued.
    obsolete = await storage.get_by_celery_id("obsolete-a")
    current = await storage.get_by_celery_id("current-b")
    assert result.failed == 1
    assert result.deferred is False
    assert persisted is True
    assert obsolete is not None and obsolete["status"] == "failed"
    assert obsolete["error_code"] == "broker_message_lost"
    assert current is not None and current["status"] == "queued"
    assert await tracking.get_observed_broker_epoch() == "epoch-b"
    assert await tracking.list_pending_broker_cleanup_generations() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_delayed_same_epoch_observer_preserves_replacement_work(
    quota_pool: asyncpg.Pool | None,
) -> None:
    # Given an observer read B before Redis was replaced with C.
    storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    tracking = TaskTrackingService(storage)
    run_id = await _prepare_run(quota_pool)
    assert await tracking.set_observed_broker_epoch("epoch-b", None)
    sampled_epoch = await tracking.get_observed_broker_epoch()
    assert sampled_epoch == "epoch-b"
    await tracking.record_task_pending(
        run_id,
        "generate_audio",
        "current-c",
        broker_generation="epoch-c",
    )
    await tracking.promote_pending_to_queued("current-c")

    # When the delayed observer uses empty-queue/online-worker evidence from C.
    result, persisted = await recover_broker_snapshot(
        fallback_epoch=None,
        snapshot=BrokerSnapshot(
            epoch=sampled_epoch,
            started_at=datetime.now(timezone.utc),
            queue_length=0,
            oldest_wait_seconds=0,
            workers_online=1,
        ),
        tracking=tracking,
        usage=UsageService(
            PostgresUsageStorage()
            if quota_pool is not None
            else InMemoryUsageStorage()
        ),
        rollback=lambda _run_id, _task_id: asyncio.sleep(0),
    )

    # Then unmarked C work survives the delayed observer's idempotent B CAS.
    current = await storage.get_by_celery_id("current-c")
    assert result.failed == 0
    assert persisted is True
    assert current is not None and current["status"] == "queued"
    assert await tracking.get_observed_broker_epoch() == "epoch-b"


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_recovery_registers_unobserved_intermediate_generation(
    quota_pool: asyncpg.Pool | None,
) -> None:
    # Given durable A while queued work belongs to unobserved generation B.
    storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    tracking = TaskTrackingService(storage)
    run_id = await _prepare_run(quota_pool)
    assert await tracking.set_observed_broker_epoch("epoch-a", None)
    await tracking.record_task_pending(
        run_id,
        "generate_audio",
        "intermediate-b",
        broker_generation="epoch-b",
    )
    await tracking.promote_pending_to_queued("intermediate-b")

    # When reconciliation samples B work on a healthy, empty C broker.
    result, persisted = await recover_broker_snapshot(
        fallback_epoch=None,
        snapshot=BrokerSnapshot(
            epoch="epoch-c",
            confirmed_epoch="epoch-c",
            active_generations=frozenset({"epoch-b"}),
            started_at=datetime.now(timezone.utc),
            queue_length=0,
            oldest_wait_seconds=0,
            workers_online=1,
        ),
        tracking=tracking,
        usage=UsageService(
            PostgresUsageStorage()
            if quota_pool is not None
            else InMemoryUsageStorage()
        ),
        rollback=lambda _run_id, _task_id: asyncio.sleep(0),
    )

    # Then B is registered atomically and converges to explainable failure.
    intermediate = await storage.get_by_celery_id("intermediate-b")
    assert result.failed == 1
    assert result.deferred is False
    assert persisted is True
    assert intermediate is not None and intermediate["status"] == "failed"
    assert intermediate["error_code"] == "broker_message_lost"
    assert await tracking.get_observed_broker_epoch() == "epoch-c"
    assert await tracking.list_pending_broker_cleanup_generations() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_recovery_defers_when_epoch_changes_after_sampling(
    quota_pool: asyncpg.Pool | None,
) -> None:
    # Given reconciliation sampled C before Redis advanced to D with D-owned work.
    storage = (
        PostgresTaskTrackingStorage()
        if quota_pool is not None
        else InMemoryTaskTrackingStorage()
    )
    tracking = TaskTrackingService(storage)
    run_id = await _prepare_run(quota_pool)
    assert await tracking.set_observed_broker_epoch("epoch-a", None)
    await tracking.record_task_pending(
        run_id,
        "generate_audio",
        "current-d",
        broker_generation="epoch-d",
    )
    await tracking.promote_pending_to_queued("current-d")

    # When final confirmation observes D instead of the sampled C generation.
    result, persisted = await recover_broker_snapshot(
        fallback_epoch=None,
        snapshot=BrokerSnapshot(
            epoch="epoch-c",
            confirmed_epoch="epoch-d",
            active_generations=frozenset(),
            started_at=datetime.now(timezone.utc),
            queue_length=0,
            oldest_wait_seconds=0,
            workers_online=1,
        ),
        tracking=tracking,
        usage=UsageService(
            PostgresUsageStorage()
            if quota_pool is not None
            else InMemoryUsageStorage()
        ),
        rollback=lambda _run_id, _task_id: asyncio.sleep(0),
    )

    # Then reconciliation defers without registering sampled or newer work.
    current = await storage.get_by_celery_id("current-d")
    assert result.failed == 0
    assert result.deferred is True
    assert persisted is False
    assert current is not None and current["status"] == "queued"
    assert await tracking.get_observed_broker_epoch() == "epoch-a"
    assert await tracking.list_pending_broker_cleanup_generations() == []
