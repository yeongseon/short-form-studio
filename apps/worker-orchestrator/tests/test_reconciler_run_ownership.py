from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from creator_service.run_service import InMemoryRunStorage, RunService
from creator_service.task_tracking_service import InMemoryTaskTrackingStorage, TaskTrackingService
from tasks.reconcile_stale_dispatches import _rollback_run


@pytest.mark.asyncio
async def test_run_rollback_skips_older_same_stage_attempt() -> None:
    runs = RunService(InMemoryRunStorage())
    tracking = TaskTrackingService(InMemoryTaskTrackingStorage())
    run = await runs.create_run(1, None, "default", current_stage="AUDIO_GENERATING")
    await tracking.record_task_pending(run.id, "generate_audio", "attempt-a")
    await tracking.mark_failed_if_pending("attempt-a", "reconciler_pending_cleanup", "cleanup")
    await tracking.record_task_queued(run.id, "generate_audio", "attempt-b")

    with patch("creator_service.run_service.run_service", runs), patch(
        "creator_service.task_tracking_service.task_tracking_service", tracking
    ):
        await _rollback_run(run.id, "attempt-a")

    current = await runs.get_run(run.id)
    assert current is not None and current.current_stage == "AUDIO_GENERATING"
    assert current.status == "pending"


@pytest.mark.asyncio
async def test_scene_task_cleanup_does_not_fail_entire_run() -> None:
    runs = RunService(InMemoryRunStorage())
    tracking = TaskTrackingService(InMemoryTaskTrackingStorage())
    run = await runs.create_run(1, None, "default", current_stage="VISUAL_ASSET_GENERATING")
    await tracking.record_task_pending(run.id, "generate_scene_image", "scene-attempt")
    await tracking.mark_failed_if_pending(
        "scene-attempt", "reconciler_pending_cleanup", "cleanup"
    )

    with patch("creator_service.run_service.run_service", runs), patch(
        "creator_service.task_tracking_service.task_tracking_service", tracking
    ):
        await _rollback_run(run.id, "scene-attempt")

    current = await runs.get_run(run.id)
    assert current is not None and current.current_stage == "VISUAL_ASSET_GENERATING"
    assert current.status == "pending"


@pytest.mark.asyncio
async def test_run_rollback_cannot_race_newer_attempt_after_ownership_read() -> None:
    runs = RunService(InMemoryRunStorage())

    class OwnershipReadBarrier(InMemoryTaskTrackingStorage):
        def __init__(self) -> None:
            super().__init__()
            self.read = asyncio.Event()
            self.resume = asyncio.Event()

        async def rollback_run_if_task_owner(
            self, celery_task_id, run_storage, run_id, eligible_task_types,
            expected_stages, rejected_statuses,
        ):
            self.read.set()
            await self.resume.wait()
            return await super().rollback_run_if_task_owner(
                celery_task_id, run_storage, run_id, eligible_task_types,
                expected_stages, rejected_statuses,
            )

    storage = OwnershipReadBarrier()
    tracking = TaskTrackingService(storage)
    run = await runs.create_run(1, None, "default", current_stage="AUDIO_GENERATING")
    await tracking.record_task_pending(run.id, "generate_audio", "attempt-a")
    await tracking.mark_failed_if_pending(
        "attempt-a", "reconciler_pending_cleanup", "cleanup"
    )

    with patch("creator_service.run_service.run_service", runs), patch(
        "creator_service.task_tracking_service.task_tracking_service", tracking
    ):
        rollback = asyncio.create_task(_rollback_run(run.id, "attempt-a"))
        await storage.read.wait()
        await tracking.record_task_queued(run.id, "generate_audio", "attempt-b")
        storage.resume.set()
        await rollback

    current = await runs.get_run(run.id)
    assert current is not None and current.current_stage == "AUDIO_GENERATING"
    assert current.status == "pending"
