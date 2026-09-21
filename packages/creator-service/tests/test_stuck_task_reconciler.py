"""Tests for PR 5: Stuck-task auto reconciler.

Validates that:
1. DispatchReconciler detects stuck running tasks (beyond threshold)
2. Stuck running tasks are marked failed with appropriate error code
3. Associated runs are rolled back to FAILED via rollback_fn
4. Fresh running tasks (below threshold) are NOT touched
5. ReconcileResult tracks stuck_failed separately from rolled_back
6. Reconciler is idempotent: second pass finds nothing after first pass
7. Threshold is safely above max Celery time_limit (660s)
8. stuck_failed only increments when mark_failed actually transitions
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from creator_service.dispatch_reconciler import DispatchReconciler, ReconcileResult
from creator_service.task_tracking_service import (
    InMemoryTaskTrackingStorage,
    TaskTrackingService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _noop_enqueue(celery_task_id: str, task_type: str, run_id: int) -> bool:
    return False


# ---------------------------------------------------------------------------
# 1. ReconcileResult has stuck_failed field
# ---------------------------------------------------------------------------


class TestReconcileResultStuckField:
    def test_reconcile_result_has_stuck_failed_field(self) -> None:
        result = ReconcileResult()
        assert hasattr(result, "stuck_failed")
        assert result.stuck_failed == 0

    def test_reconcile_result_stuck_failed_default_zero(self) -> None:
        result = ReconcileResult()
        assert result.stuck_failed == 0
        assert result.reenqueued == 0
        assert result.rolled_back == 0


# ---------------------------------------------------------------------------
# 2. DispatchReconciler accepts stuck_threshold_seconds
# ---------------------------------------------------------------------------


class TestReconcilerStuckThreshold:
    def test_reconciler_accepts_stuck_threshold(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)
        reconciler = DispatchReconciler(
            task_tracking_service=service,
            enqueue_fn=_noop_enqueue,
            stuck_threshold_seconds=700,
        )
        assert reconciler._stuck_threshold_seconds == 700

    def test_default_stuck_threshold_is_900(self) -> None:
        """Default must exceed max Celery time_limit (660s) + scheduler jitter."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)
        reconciler = DispatchReconciler(
            task_tracking_service=service,
            enqueue_fn=_noop_enqueue,
        )
        assert reconciler._stuck_threshold_seconds == 900
        # Must be safely above the max hard time_limit (660s)
        assert reconciler._stuck_threshold_seconds > 660


    def test_unsafe_threshold_raises_value_error(self) -> None:
        """Constructor must reject stuck_threshold_seconds <= 660."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)
        with pytest.raises(ValueError, match="must exceed"):
            DispatchReconciler(
                task_tracking_service=service,
                enqueue_fn=_noop_enqueue,
                stuck_threshold_seconds=660,
            )

# ---------------------------------------------------------------------------
# 3. Reconciler detects stuck running tasks
# ---------------------------------------------------------------------------


class TestReconcilerFindsStuckRunningTasks:
    def test_stuck_running_task_is_marked_failed(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "generate_script",
                "celery_task_id": "celery-stuck-1", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1200),
            })

            rolled_back: list[tuple[int, str]] = []
            async def fake_rollback(run_id: int, celery_task_id: str) -> None:
                rolled_back.append((run_id, celery_task_id))

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                rollback_fn=fake_rollback, stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()
            assert result.stuck_failed == 1
            assert rolled_back == [(1, "celery-stuck-1")]

            task_row = await storage.get_by_celery_id("celery-stuck-1")
            assert task_row is not None
            assert task_row["status"] == "failed"
            assert task_row["error_code"] == "stuck_running_timeout"

        asyncio.run(_run())

    def test_fresh_running_task_is_not_touched(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 2, "task_type": "generate_audio",
                "celery_task_id": "celery-fresh", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=60),
            })

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()
            assert result.stuck_failed == 0

            task_row = await storage.get_by_celery_id("celery-fresh")
            assert task_row is not None
            assert task_row["status"] == "running"

        asyncio.run(_run())

    def test_task_at_660s_is_not_reconciled(self) -> None:
        """A task running for 660s (max hard time_limit) must NOT be touched.
        Regression test: threshold must exceed Celery's max time_limit."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 3, "task_type": "render_video",
                "celery_task_id": "celery-at-hard-limit", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=660),
            })

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()
            assert result.stuck_failed == 0

            task_row = await storage.get_by_celery_id("celery-at-hard-limit")
            assert task_row is not None
            assert task_row["status"] == "running"

        asyncio.run(_run())

    def test_task_past_threshold_is_reconciled(self) -> None:
        """A task running past the stuck threshold IS reconciled."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 4, "task_type": "render_video",
                "celery_task_id": "celery-past-threshold", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1000),
            })

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()
            assert result.stuck_failed == 1

            task_row = await storage.get_by_celery_id("celery-past-threshold")
            assert task_row is not None
            assert task_row["status"] == "failed"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 4. Both stale pending + stuck running in same pass
# ---------------------------------------------------------------------------


class TestReconcilerHandlesBothTypes:
    def test_both_stale_pending_and_stuck_running(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 10, "task_type": "generate_script",
                "celery_task_id": "celery-stale-pending", "status": "pending",
                "attempt": 1,
                "created_at": datetime.now(timezone.utc) - timedelta(seconds=300),
            })
            await storage.create_task({
                "run_id": 20, "task_type": "generate_audio",
                "celery_task_id": "celery-stuck-running", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1200),
            })

            rolled_back: list[int] = []
            async def fake_rollback(run_id: int, celery_task_id: str) -> None:
                rolled_back.append(run_id)

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                rollback_fn=fake_rollback,
                threshold_seconds=120, stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()
            assert result.rolled_back == 1
            assert result.stuck_failed == 1
            assert set(rolled_back) == {10, 20}

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 5. Idempotency
# ---------------------------------------------------------------------------


class TestStuckReconcilerIdempotency:
    def test_second_pass_finds_no_stuck_tasks(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "generate_script",
                "celery_task_id": "celery-stuck-idem", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1200),
            })

            async def noop_rollback(run_id: int, celery_task_id: str) -> None:
                pass

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                rollback_fn=noop_rollback, stuck_threshold_seconds=900,
            )

            r1 = await reconciler.reconcile()
            assert r1.stuck_failed == 1

            r2 = await reconciler.reconcile()
            assert r2.stuck_failed == 0

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 6. Rollback failure records error
# ---------------------------------------------------------------------------


class TestStuckTaskRollbackFailure:
    def test_rollback_failure_records_error(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "generate_script",
                "celery_task_id": "celery-stuck-rb-fail", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1200),
            })

            async def failing_rollback(run_id: int, celery_task_id: str) -> None:
                raise RuntimeError("DB connection lost")

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                rollback_fn=failing_rollback, stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()

            assert result.stuck_failed == 1
            assert len(result.errors) == 1
            assert "DB connection lost" in result.errors[0]

            task_row = await storage.get_by_celery_id("celery-stuck-rb-fail")
            assert task_row is not None
            assert task_row["status"] == "failed"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 7. No rollback_fn — still marks failed
# ---------------------------------------------------------------------------


class TestStuckTaskNoRollbackFn:
    def test_stuck_task_marked_failed_without_rollback_fn(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "generate_video",
                "celery_task_id": "celery-stuck-no-rb", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1200),
            })

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                rollback_fn=None, stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()

            assert result.stuck_failed == 1
            task_row = await storage.get_by_celery_id("celery-stuck-no-rb")
            assert task_row is not None
            assert task_row["status"] == "failed"
            assert task_row["error_code"] == "stuck_running_timeout"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 8. stuck_failed only increments on actual transition
# ---------------------------------------------------------------------------


class TestStuckFailedOnlyOnTransition:
    def test_stuck_failed_not_incremented_when_task_already_succeeded(self) -> None:
        """If task transitions to success between scan and mark_failed,
        stuck_failed should NOT increment."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            # Create a task that appears stuck
            await storage.create_task({
                "run_id": 1, "task_type": "generate_script",
                "celery_task_id": "celery-race-success", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1200),
            })

            # Simulate: task completes between scan and mark_failed
            # by marking it success before reconciler acts on it
            original_find = service.find_stuck_tasks

            async def find_then_succeed(threshold_seconds: int):
                tasks = await original_find(threshold_seconds)
                # Simulate worker completing the task
                await service.mark_success("celery-race-success")
                return tasks

            service.find_stuck_tasks = find_then_succeed  # type: ignore[assignment]

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()

            # mark_failed returns None (task is success, guard blocks)
            assert result.stuck_failed == 0

            # Task should still be success
            task_row = await storage.get_by_celery_id("celery-race-success")
            assert task_row is not None
            assert task_row["status"] == "success"

        asyncio.run(_run())

    def test_mark_failed_exception_records_error_and_no_increment(self) -> None:
        """If mark_failed raises, error should be recorded and stuck_failed not incremented."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "generate_script",
                "celery_task_id": "celery-mark-fail-err", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1200),
            })

            original_mark = service.mark_failed_if_running

            async def failing_mark(*args: Any, **kwargs: Any):
                raise RuntimeError("Storage unavailable")

            service.mark_failed_if_running = failing_mark  # type: ignore[assignment]

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()

            assert result.stuck_failed == 0
            assert len(result.errors) >= 1
            assert any("Storage unavailable" in e for e in result.errors)

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 9. Integration: reconcile_stale_dispatches wiring
# ---------------------------------------------------------------------------


class TestReconcileStaleDispatchesIntegration:
    def test_reconcile_once_uses_900_stuck_threshold(self) -> None:
        """_reconcile_once must use stuck_threshold_seconds=900 (above max time_limit=660)."""
        import sys
        if "apps/worker-orchestrator" not in sys.path:
            sys.path.insert(0, "apps/worker-orchestrator")

        from unittest.mock import patch, AsyncMock, MagicMock

        captured_kwargs: dict[str, Any] = {}
        original_init = DispatchReconciler.__init__

        def capturing_init(self_inner: Any, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)
            original_init(self_inner, **kwargs)

        async def _run() -> None:
            mock_tracking = MagicMock()
            mock_tracking.find_stale_pending_tasks = AsyncMock(return_value=[])
            mock_tracking.find_stuck_tasks = AsyncMock(return_value=[])

            with patch("creator_service.task_tracking_service.task_tracking_service", mock_tracking), \
                 patch.object(DispatchReconciler, "__init__", capturing_init):
                from tasks.reconcile_stale_dispatches import _reconcile_once
                summary = await _reconcile_once()

            assert captured_kwargs.get("stuck_threshold_seconds") == 900
            assert "stuck_failed" in summary

        asyncio.run(_run())

    def test_reconcile_summary_includes_stuck_failed(self) -> None:
        """The summary dict must include stuck_failed key."""
        import sys
        if "apps/worker-orchestrator" not in sys.path:
            sys.path.insert(0, "apps/worker-orchestrator")

        from unittest.mock import patch, AsyncMock, MagicMock

        async def _run() -> None:
            mock_tracking = MagicMock()
            mock_tracking.find_stale_pending_tasks = AsyncMock(return_value=[])
            mock_tracking.find_stuck_tasks = AsyncMock(return_value=[])

            with patch("creator_service.task_tracking_service.task_tracking_service", mock_tracking):
                from tasks.reconcile_stale_dispatches import _reconcile_once
                summary = await _reconcile_once()

            assert "stuck_failed" in summary
            assert summary["stuck_failed"] == 0

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 10. Threshold safety: must exceed max Celery time_limit
# ---------------------------------------------------------------------------


class TestThresholdSafety:
    def test_threshold_exceeds_max_celery_time_limit(self) -> None:
        """Stuck threshold in production wiring must exceed the longest Celery time_limit.
        Current max: render_video/generate_scene_image at time_limit=660s."""
        MAX_CELERY_TIME_LIMIT = 660  # render_video, generate_scene_image

        import sys
        if "apps/worker-orchestrator" not in sys.path:
            sys.path.insert(0, "apps/worker-orchestrator")

        import inspect
        from tasks.reconcile_stale_dispatches import _reconcile_once
        source = inspect.getsource(_reconcile_once)

        # Extract the stuck_threshold_seconds value
        import re
        match = re.search(r"stuck_threshold_seconds\s*=\s*(\d+)", source)
        assert match is not None, "stuck_threshold_seconds must be set in _reconcile_once"
        threshold = int(match.group(1))

        assert threshold > MAX_CELERY_TIME_LIMIT, (
            f"stuck_threshold_seconds ({threshold}) must exceed max Celery "
            f"time_limit ({MAX_CELERY_TIME_LIMIT}) to avoid false positives"
        )


# ---------------------------------------------------------------------------
# 11. Rollback only after mark_failed succeeds (CAS-then-rollback ordering)
# ---------------------------------------------------------------------------


class TestRollbackOnlyAfterMarkFailed:
    def test_rollback_called_only_when_mark_failed_succeeds(self) -> None:
        """Rollback must only happen after mark_failed confirms the task
        actually transitioned from running → failed (CAS guard)."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "render_video",
                "celery_task_id": "celery-cas-test", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1200),
            })

            call_order: list[str] = []

            async def tracking_rollback(run_id: int, celery_task_id: str) -> None:
                call_order.append("rollback")

            # Monkey-patch mark_failed to record call order
            original_mark = service.mark_failed_if_running
            async def ordered_mark(*args: Any, **kwargs: Any):
                call_order.append("mark_failed")
                return await original_mark(*args, **kwargs)
            service.mark_failed_if_running = ordered_mark  # type: ignore[assignment]

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                rollback_fn=tracking_rollback, stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()
            assert result.stuck_failed == 1
            # mark_failed MUST be called before rollback
            assert call_order == ["mark_failed", "rollback"]

        asyncio.run(_run())

    def test_no_rollback_when_task_already_succeeded(self) -> None:
        """If task succeeded (mark_failed returns None), rollback must NOT be called."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "generate_script",
                "celery_task_id": "celery-race-no-rb", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1200),
            })

            # Simulate task completing between scan and mark_failed
            original_find = service.find_stuck_tasks
            async def find_then_succeed(threshold_seconds: int):
                tasks = await original_find(threshold_seconds)
                await service.mark_success("celery-race-no-rb")
                return tasks
            service.find_stuck_tasks = find_then_succeed  # type: ignore[assignment]

            rollback_called = False
            async def should_not_rollback(run_id: int, celery_task_id: str) -> None:
                nonlocal rollback_called
                rollback_called = True

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                rollback_fn=should_not_rollback, stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()

            assert result.stuck_failed == 0
            assert not rollback_called, "Rollback must NOT be called when task already succeeded"

            task_row = await storage.get_by_celery_id("celery-race-no-rb")
            assert task_row is not None
            assert task_row["status"] == "success"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 12. Stage name correctness: _NON_TERMINAL_GENERATING_STAGES uses real RunStage values
# ---------------------------------------------------------------------------


class TestStageNameCorrectness:
    def test_non_terminal_stages_match_run_stage_enum(self) -> None:
        """All stage names in _NON_TERMINAL_GENERATING_STAGES must be valid
        RunStage enum values, not legacy names."""
        import sys
        if "apps/worker-orchestrator" not in sys.path:
            sys.path.insert(0, "apps/worker-orchestrator")

        from creator_domain.models.stage import RunStage
        from tasks.reconcile_stale_dispatches import _NON_TERMINAL_GENERATING_STAGES

        valid_stages = {s.value for s in RunStage}
        invalid = _NON_TERMINAL_GENERATING_STAGES - valid_stages
        assert not invalid, (
            f"_NON_TERMINAL_GENERATING_STAGES contains invalid stage names: {invalid}. "
            f"Valid stages: {sorted(valid_stages)}"
        )

    def test_all_generating_stages_are_included(self) -> None:
        """Every *_GENERATING stage from RunStage must be in the rollback allowlist."""
        import sys
        if "apps/worker-orchestrator" not in sys.path:
            sys.path.insert(0, "apps/worker-orchestrator")

        from creator_domain.models.stage import RunStage
        from tasks.reconcile_stale_dispatches import _NON_TERMINAL_GENERATING_STAGES

        generating_stages = {s.value for s in RunStage if s.value.endswith("_GENERATING")}
        missing = generating_stages - _NON_TERMINAL_GENERATING_STAGES
        assert not missing, (
            f"_NON_TERMINAL_GENERATING_STAGES is missing generating stages: {missing}"
        )




class TestMarkFailedIfRunningCAS:
    """Tests for the mark_failed_if_running CAS guard.

    The CAS guard ensures that only tasks currently in 'running' state
    are transitioned to 'failed'.  Tasks that transitioned to revoked,
    rejected, or success between the scan and the mark are left alone.
    """

    def test_cas_succeeds_for_running_task(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "render_video",
                "celery_task_id": "cas-ok-1", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=100),
            })
            result = await service.mark_failed_if_running(
                "cas-ok-1", error_code="stuck", error_message="timed out"
            )
            assert result is not None
            assert result.status == "failed"

        asyncio.run(_run())

    def test_cas_skips_revoked_task(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "render_video",
                "celery_task_id": "cas-revoked-1", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=100),
            })
            await service.mark_revoked("cas-revoked-1")
            result = await service.mark_failed_if_running(
                "cas-revoked-1", error_code="stuck", error_message="timed out"
            )
            assert result is None
            task = await storage.get_by_celery_id("cas-revoked-1")
            assert task["status"] == "revoked"

        asyncio.run(_run())

    def test_cas_skips_rejected_task(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "render_video",
                "celery_task_id": "cas-rejected-1", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=100),
            })
            await service.mark_rejected("cas-rejected-1")
            result = await service.mark_failed_if_running(
                "cas-rejected-1", error_code="stuck", error_message="timed out"
            )
            assert result is None
            task = await storage.get_by_celery_id("cas-rejected-1")
            assert task["status"] == "rejected"

        asyncio.run(_run())

    def test_cas_skips_success_task(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "render_video",
                "celery_task_id": "cas-success-1", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=100),
            })
            await service.mark_success("cas-success-1")
            result = await service.mark_failed_if_running(
                "cas-success-1", error_code="stuck", error_message="timed out"
            )
            assert result is None
            task = await storage.get_by_celery_id("cas-success-1")
            assert task["status"] == "success"

        asyncio.run(_run())

    def test_cas_returns_none_for_unknown_id(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            result = await service.mark_failed_if_running(
                "nonexistent", error_code="stuck", error_message="timed out"
            )
            assert result is None

        asyncio.run(_run())

    def test_reconciler_no_rollback_on_cas_miss(self) -> None:
        """Full integration: task revoked between scan and mark → no rollback."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await storage.create_task({
                "run_id": 1, "task_type": "render_video",
                "celery_task_id": "race-revoked-1", "status": "running",
                "attempt": 1,
                "started_at": datetime.now(timezone.utc) - timedelta(seconds=1200),
            })

            rolled_back: list[tuple[int, str]] = []
            async def fake_rollback(run_id: int, celery_task_id: str) -> None:
                rolled_back.append((run_id, celery_task_id))

            # Patch find_stuck_tasks: return task while running, then revoke
            original_find = service.find_stuck_tasks
            async def patched_find(threshold_seconds: int = 600) -> list:
                tasks = await original_find(threshold_seconds)
                # Revoke AFTER scan but BEFORE mark — simulates race
                await service.mark_revoked("race-revoked-1")
                return tasks
            service.find_stuck_tasks = patched_find  # type: ignore[assignment]

            reconciler = DispatchReconciler(
                task_tracking_service=service, enqueue_fn=_noop_enqueue,
                rollback_fn=fake_rollback, stuck_threshold_seconds=900,
            )
            result = await reconciler.reconcile()

            assert result.stuck_failed == 0
            assert len(rolled_back) == 0
            task = await storage.get_by_celery_id("race-revoked-1")
            assert task["status"] == "revoked"

        asyncio.run(_run())
