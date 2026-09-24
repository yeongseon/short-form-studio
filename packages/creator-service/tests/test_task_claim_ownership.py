import pytest
from creator_service import db
from creator_service.memory_task_tracking_storage import InMemoryTaskTrackingStorage
from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage
from creator_service.task_tracking_service import TaskTrackingService

from .quota_dispatch_support import quota_pool as quota_pool


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_only_claim_owner_can_finalize_timeout(quota_pool: object) -> None:
    # Given two deliveries for the same logical task, with A owning the running row.
    storage = PostgresTaskTrackingStorage() if quota_pool is not None else InMemoryTaskTrackingStorage()
    tracking = TaskTrackingService(storage)
    if quota_pool is not None:
        pool = await db.get_pool()
        await pool.execute("INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1)")
        await pool.execute("INSERT INTO creator_runs (id, project_id, workspace_id, current_stage) VALUES (1, 1, 1, 'AUDIO_GENERATING')")
    winner = await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-a")
    assert winner is not None and winner.status == "running"
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-b") is None

    # When B tries to finalize a timeout before A.
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-b", "INTERNAL", "timed out") is None
    assert (await storage.get_by_celery_id("delivery-1"))["status"] == "running"

    # Then only the matching owner can transition the task to failed.
    failed = await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "timed out")
    assert failed is not None and failed.status == "failed"
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "timed out") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_stale_success_cannot_finalize_newer_claim(quota_pool: object) -> None:
    # Given a newer worker claimed the same task after the previous attempt failed.
    storage = PostgresTaskTrackingStorage() if quota_pool is not None else InMemoryTaskTrackingStorage()
    tracking = TaskTrackingService(storage)
    if quota_pool is not None:
        pool = await db.get_pool()
        await pool.execute("INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1)")
        await pool.execute("INSERT INTO creator_runs (id, project_id, workspace_id, current_stage) VALUES (1, 1, 1, 'AUDIO_GENERATING')")
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-a")
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "retry")
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-b")

    # When A reports success after B has won the retry claim.
    assert await tracking.mark_success_if_claimed("delivery-1", "owner-a") is None

    # Then B's running claim remains untouched until B finalizes it.
    assert (await storage.get_by_celery_id("delivery-1"))["status"] == "running"
    assert await tracking.mark_success_if_claimed("delivery-1", "owner-b")
    assert (await storage.get_by_celery_id("delivery-1"))["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_stale_failure_cannot_finalize_newer_claim(quota_pool: object) -> None:
    # Given a retried delivery B after A has failed.
    storage = PostgresTaskTrackingStorage() if quota_pool is not None else InMemoryTaskTrackingStorage()
    tracking = TaskTrackingService(storage)
    if quota_pool is not None:
        pool = await db.get_pool()
        await pool.execute("INSERT INTO creator_projects (id, workspace_id) VALUES (1, 1)")
        await pool.execute("INSERT INTO creator_runs (id, project_id, workspace_id, current_stage) VALUES (1, 1, 1, 'AUDIO_GENERATING')")
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-a")
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "retry")
    assert await tracking.record_task_start(1, "generate_audio", "delivery-1", claim_token="owner-b")

    # When A reports its late failure.
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-a", "INTERNAL", "late") is None

    # Then B remains running until B itself fails.
    assert (await storage.get_by_celery_id("delivery-1"))["status"] == "running"
    assert await tracking.mark_failed_if_claimed("delivery-1", "owner-b", "INTERNAL", "failed")
