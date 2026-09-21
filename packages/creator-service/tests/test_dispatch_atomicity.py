"""Tests for PR B: Dispatch atomicity — DB-first dispatch record + reconciler.

Validates that:
1. Task records are created as 'pending' BEFORE broker enqueue
2. Pending → queued promotion happens after successful enqueue
3. Enqueue failures leave task as 'pending' for reconciler recovery
4. Reconciler finds and re-enqueues stale pending tasks
5. claim_running accepts 'pending' status (worker races promote)
6. Transaction atomicity: CAS failure → no pending record created
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from creator_service.task_tracking_service import (
    InMemoryTaskTrackingStorage,
    TaskTrackingService,
)


# ---------------------------------------------------------------------------
# 1. claim_running must accept 'pending' status
# ---------------------------------------------------------------------------


class TestClaimRunningPending:
    """claim_running should also transition from 'pending' to 'running'."""

    def test_claim_running_from_pending(self) -> None:
        """A task in 'pending' state should be claimable."""
        storage = InMemoryTaskTrackingStorage()

        async def _run() -> None:
            row = await storage.create_task(
                {
                    "run_id": 1,
                    "task_type": "generate_script",
                    "celery_task_id": "celery-abc",
                    "status": "pending",
                    "attempt": 1,
                }
            )
            assert row is not None
            assert row["status"] == "pending"

            claimed = await storage.claim_running(row["id"], started_at=datetime.now(timezone.utc))
            assert claimed is not None
            assert claimed["status"] == "running"

        asyncio.run(_run())

    def test_claim_running_from_pending_only_one_winner(self) -> None:
        """Two concurrent claims on a 'pending' task — only one should win."""
        storage = InMemoryTaskTrackingStorage()

        async def _run() -> None:
            row = await storage.create_task(
                {
                    "run_id": 1,
                    "task_type": "generate_script",
                    "celery_task_id": "celery-race",
                    "status": "pending",
                    "attempt": 1,
                }
            )
            assert row is not None

            now = datetime.now(timezone.utc)
            claim1 = await storage.claim_running(row["id"], started_at=now)
            claim2 = await storage.claim_running(row["id"], started_at=now)

            assert claim1 is not None
            assert claim2 is None  # Second claim fails

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 2. record_task_pending creates a 'pending' task
# ---------------------------------------------------------------------------


class TestRecordTaskPending:
    """TaskTrackingService.record_task_pending creates a task with status='pending'."""

    def test_record_task_pending_creates_pending_record(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            task = await service.record_task_pending(
                run_id=1,
                task_type="generate_script",
                celery_task_id="celery-pre-123",
            )
            assert task.status == "pending"
            assert task.celery_task_id == "celery-pre-123"
            assert task.run_id == 1

        asyncio.run(_run())

    def test_record_task_pending_idempotent_on_existing_pending(self) -> None:
        """If already pending, re-recording should succeed (idempotent)."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            task1 = await service.record_task_pending(1, "generate_script", "celery-dup")
            task2 = await service.record_task_pending(1, "generate_script", "celery-dup")
            assert task1.id == task2.id

        asyncio.run(_run())

    def test_record_task_pending_rejects_if_already_running(self) -> None:
        """If task is already running, pending should not overwrite it."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            # Create and claim
            task = await service.record_task_pending(1, "generate_script", "celery-running")
            claimed = await service.record_task_start(1, "generate_script", "celery-running")
            assert claimed is not None
            assert claimed.status == "running"

            # Try to re-register as pending — should fail (return None or raise)
            with pytest.raises(ValueError):
                await service.record_task_pending(1, "generate_script", "celery-running")

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 3. promote_pending_to_queued transitions pending → queued
# ---------------------------------------------------------------------------


class TestPromotePendingToQueued:
    """TaskTrackingService.promote_pending_to_queued transitions pending → queued."""

    def test_promote_pending_to_queued_succeeds(self) -> None:
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            task = await service.record_task_pending(1, "generate_script", "celery-promote")
            promoted = await service.promote_pending_to_queued("celery-promote")
            assert promoted is not None
            assert promoted.status == "queued"

        asyncio.run(_run())

    def test_promote_already_running_returns_none(self) -> None:
        """If worker already claimed (pending → running), promote should return None."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            await service.record_task_pending(1, "generate_script", "celery-fast-worker")
            # Worker claims immediately
            await service.record_task_start(1, "generate_script", "celery-fast-worker")
            # Now try to promote — already running
            promoted = await service.promote_pending_to_queued("celery-fast-worker")
            assert promoted is None

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 4. list_stale_pending_tasks finds old pending tasks
# ---------------------------------------------------------------------------


class TestListStalePendingTasks:
    """Storage should find pending tasks older than a threshold."""

    def test_list_stale_pending_tasks_finds_old_entries(self) -> None:
        storage = InMemoryTaskTrackingStorage()

        async def _run() -> None:
            row = await storage.create_task(
                {
                    "run_id": 1,
                    "task_type": "generate_script",
                    "celery_task_id": "celery-stale",
                    "status": "pending",
                    "attempt": 1,
                    "created_at": datetime.now(timezone.utc) - timedelta(seconds=120),
                }
            )
            assert row is not None

            # Fresh task should not appear
            await storage.create_task(
                {
                    "run_id": 2,
                    "task_type": "generate_audio",
                    "celery_task_id": "celery-fresh",
                    "status": "pending",
                    "attempt": 1,
                }
            )

            stale = await storage.list_stale_pending_tasks(threshold_seconds=60)
            assert len(stale) == 1
            assert stale[0]["celery_task_id"] == "celery-stale"

        asyncio.run(_run())

    def test_list_stale_pending_tasks_excludes_queued(self) -> None:
        """Only 'pending' tasks, not 'queued' or 'running'."""
        storage = InMemoryTaskTrackingStorage()

        async def _run() -> None:
            await storage.create_task(
                {
                    "run_id": 1,
                    "task_type": "generate_script",
                    "celery_task_id": "celery-queued",
                    "status": "queued",
                    "attempt": 1,
                    "created_at": datetime.now(timezone.utc) - timedelta(seconds=120),
                }
            )

            stale = await storage.list_stale_pending_tasks(threshold_seconds=60)
            assert len(stale) == 0

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 5. Dispatch reconciler
# ---------------------------------------------------------------------------


class TestDispatchReconciler:
    """Reconciler re-enqueues stale pending tasks or rolls back runs."""

    def test_reconcile_stale_pending_reenqueues(self) -> None:
        """Reconciler should attempt to re-enqueue stale pending tasks."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)
        enqueued: list[dict[str, Any]] = []

        async def _run() -> None:
            from creator_service.dispatch_reconciler import DispatchReconciler

            row = await storage.create_task(
                {
                    "run_id": 1,
                    "task_type": "generate_script",
                    "celery_task_id": "celery-stale-1",
                    "status": "pending",
                    "attempt": 1,
                    "created_at": datetime.now(timezone.utc) - timedelta(seconds=120),
                }
            )
            assert row is not None

            async def fake_enqueue(celery_task_id: str, task_type: str, run_id: int) -> bool:
                enqueued.append(
                    {"task_id": celery_task_id, "task_type": task_type, "run_id": run_id}
                )
                return True

            reconciler = DispatchReconciler(
                task_tracking_service=service,
                enqueue_fn=fake_enqueue,
                threshold_seconds=60,
            )
            result = await reconciler.reconcile()
            assert result.reenqueued == 1
            assert result.rolled_back == 0
            assert len(enqueued) == 1
            assert enqueued[0]["task_id"] == "celery-stale-1"

        asyncio.run(_run())

    def test_reconcile_reenqueue_failure_rolls_back(self) -> None:
        """If re-enqueue fails, reconciler should roll back the run stage."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)
        rolled_back_runs: list[int] = []

        async def _run() -> None:
            from creator_service.dispatch_reconciler import DispatchReconciler

            await storage.create_task(
                {
                    "run_id": 1,
                    "task_type": "generate_script",
                    "celery_task_id": "celery-fail-enqueue",
                    "status": "pending",
                    "attempt": 1,
                    "created_at": datetime.now(timezone.utc) - timedelta(seconds=120),
                }
            )

            async def failing_enqueue(celery_task_id: str, task_type: str, run_id: int) -> bool:
                return False

            async def fake_rollback(run_id: int, celery_task_id: str) -> None:
                rolled_back_runs.append(run_id)

            reconciler = DispatchReconciler(
                task_tracking_service=service,
                enqueue_fn=failing_enqueue,
                rollback_fn=fake_rollback,
                threshold_seconds=60,
            )
            result = await reconciler.reconcile()
            assert result.reenqueued == 0
            assert result.rolled_back == 1
            assert rolled_back_runs == [1]

        asyncio.run(_run())

    def test_reconcile_skips_fresh_pending_tasks(self) -> None:
        """Tasks pending for less than threshold should not be reconciled."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            from creator_service.dispatch_reconciler import DispatchReconciler

            await storage.create_task(
                {
                    "run_id": 1,
                    "task_type": "generate_script",
                    "celery_task_id": "celery-recent",
                    "status": "pending",
                    "attempt": 1,
                    # created_at defaults to now — should be fresh
                }
            )

            async def should_not_be_called(
                celery_task_id: str, task_type: str, run_id: int
            ) -> bool:
                raise AssertionError("Should not enqueue fresh tasks")

            reconciler = DispatchReconciler(
                task_tracking_service=service,
                enqueue_fn=should_not_be_called,
                threshold_seconds=60,
            )
            result = await reconciler.reconcile()
            assert result.reenqueued == 0
            assert result.rolled_back == 0

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 6. Pre-generated task_id in dispatch
# ---------------------------------------------------------------------------


class TestPreGeneratedTaskId:
    """_dispatch_task should accept and use a pre-generated task_id."""

    def test_dispatch_task_uses_pre_generated_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from creator_service.task_dispatch_service import TaskDispatchService

        service = TaskDispatchService()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        received_task_id: list[str | None] = []

        class _FakeTask:
            def apply_async(
                self,
                *,
                args: list[Any],
                kwargs: dict[str, Any],
                headers: dict[str, str],
                task_id: str | None = None,
            ) -> Any:
                received_task_id.append(task_id)
                return SimpleNamespace(id=task_id or "fallback-id")

        def fake_import_module(name: str) -> Any:
            if name == "tasks.generate_script":
                return SimpleNamespace(generate_script=_FakeTask())
            if name == "creator_service.telemetry":
                return SimpleNamespace(get_trace_headers=lambda: {})
            raise AssertionError(f"unexpected import: {name}")

        monkeypatch.setattr(
            "creator_service.task_dispatch_service.import_module", fake_import_module
        )

        result = service._dispatch_task(
            module_name="tasks.generate_script",
            task_attr="generate_script",
            run_id=1,
            args=[1, "idea", "model", None],
            task_id="pre-generated-123",
        )
        assert result == "pre-generated-123"
        assert received_task_id == ["pre-generated-123"]


# ---------------------------------------------------------------------------
# 7. Postgres storage: list_stale_pending_tasks and claim_running with 'pending'
# ---------------------------------------------------------------------------


class TestPostgresTaskTrackingStoragePendingSupport:
    """Postgres storage must support 'pending' status in claim_running and stale queries."""

    def test_claim_running_includes_pending_in_where(self) -> None:
        """Verify the Postgres claim_running SQL includes 'pending' in its WHERE clause."""
        from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage
        import inspect

        source = inspect.getsource(PostgresTaskTrackingStorage.claim_running)
        assert "'pending'" in source or '"pending"' in source, (
            "claim_running SQL must include 'pending' in WHERE status IN clause"
        )

    def test_list_stale_pending_tasks_method_exists(self) -> None:
        """Postgres storage must have list_stale_pending_tasks method."""
        from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage

        assert hasattr(PostgresTaskTrackingStorage, "list_stale_pending_tasks")


# ---------------------------------------------------------------------------
# 8. E2E: cas_dispatch_with_rollback threads task_id and promotes pending
# ---------------------------------------------------------------------------


class TestCasDispatchEndToEnd:
    """Full cas_dispatch_with_rollback flow: pending → dispatch with task_id → promoted."""

    def test_cas_dispatch_threads_task_id_and_promotes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pre-generated task_id should flow through dispatcher and task promoted to queued."""
        from creator_service.task_dispatch_service import TaskDispatchService

        service = TaskDispatchService()
        tracking_storage = InMemoryTaskTrackingStorage()
        tracking_svc = TaskTrackingService(tracking_storage)

        # Track dispatcher calls
        dispatcher_calls: list[dict[str, Any]] = []

        def fake_dispatcher(run_id: int, idea_brief: str, model_key: str,
                            instructions: str | None, task_id: str | None = None) -> str:
            dispatcher_calls.append({"run_id": run_id, "task_id": task_id})
            return task_id or "fallback-id"

        # Fake run service
        class _FakeStorage:
            async def conditional_update_run(self, run_id, updates, *,
                                             expected_stages, workspace_id=None,
                                             rejected_statuses=None):
                return True, {"current_stage": updates.get("current_stage", "GENERATING_SCRIPT")}

        class _FakeRunService:
            storage = _FakeStorage()
            async def get_run(self, run_id, **kwargs):
                return SimpleNamespace(status="running", project_id=1)

        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        # Patch import_module to return our tracking service
        _real_import = __import__("importlib").import_module

        def patched_import(name: str):
            if name == "creator_service.task_tracking_service":
                return SimpleNamespace(task_tracking_service=tracking_svc)
            return _real_import(name)

        monkeypatch.setattr(
            "creator_service.task_dispatch_service.import_module", patched_import
        )

        # Give dispatcher the right __name__ for _DISPATCH_TASK_TYPES lookup
        fake_dispatcher.__name__ = "dispatch_generate_script"

        async def _run() -> None:
            result = await service.cas_dispatch_with_rollback(
                run_id=1,
                expected_stages=frozenset({"IDEA_REVIEW"}),
                target_stage="GENERATING_SCRIPT",
                dispatcher=fake_dispatcher,
                dispatcher_args={"run_id": 1, "idea_brief": "test", "model_key": "gpt", "instructions": None},
                run_service=_FakeRunService(),
                rollback_stage="IDEA_REVIEW",
                rollback_restart_from=None,
                enqueue_error_detail="dispatch failed",
            )

            # Verify dispatcher was called with pre_generated_task_id
            assert len(dispatcher_calls) == 1
            task_id_used = dispatcher_calls[0]["task_id"]
            assert task_id_used is not None, "task_id should be injected into dispatcher"

            # Verify task was promoted to 'queued'
            task_row = await tracking_storage.get_by_celery_id(task_id_used)
            assert task_row is not None
            assert task_row["status"] == "queued", f"Expected queued, got {task_row['status']}"

            # Verify result
            assert result["task_id"] == task_id_used

        asyncio.run(_run())

    def test_cas_dispatch_pending_failure_rolls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If record_task_pending fails, CAS should roll back and raise 503."""
        from creator_domain.exceptions import ServiceUnavailableError
        from creator_service.task_dispatch_service import TaskDispatchService

        service = TaskDispatchService()
        rollback_calls: list[dict[str, Any]] = []
        dispatcher_called = False

        def fake_dispatcher(**kwargs: Any) -> str:
            nonlocal dispatcher_called
            dispatcher_called = True
            return "should-not-reach"

        class _FakeStorage:
            async def conditional_update_run(self, run_id, updates, *,
                                             expected_stages, workspace_id=None,
                                             rejected_statuses=None):
                rollback_calls.append({"run_id": run_id, "updates": updates})
                return True, {"current_stage": updates.get("current_stage")}

        class _FakeRunService:
            storage = _FakeStorage()
            async def get_run(self, run_id, **kwargs):
                return SimpleNamespace(status="running", project_id=1)

        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        class _FailingTrackingService:
            async def record_task_pending(self, run_id, task_type, celery_task_id):
                raise RuntimeError("DB connection lost")

        _real_import = __import__("importlib").import_module

        def patched_import(name: str):
            if name == "creator_service.task_tracking_service":
                return SimpleNamespace(task_tracking_service=_FailingTrackingService())
            return _real_import(name)

        monkeypatch.setattr(
            "creator_service.task_dispatch_service.import_module", patched_import
        )

        fake_dispatcher.__name__ = "dispatch_generate_script"

        async def _run() -> None:
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await service.cas_dispatch_with_rollback(
                    run_id=1,
                    expected_stages=frozenset({"IDEA_REVIEW"}),
                    target_stage="GENERATING_SCRIPT",
                    dispatcher=fake_dispatcher,
                    dispatcher_args={},
                    run_service=_FakeRunService(),
                    rollback_stage="IDEA_REVIEW",
                    rollback_restart_from=None,
                    enqueue_error_detail="dispatch failed",
                )
            assert exc_info.value.http_status_code == 503
            assert not dispatcher_called, "Dispatcher should not be called after pending failure"
            # First call = CAS set target, second call = rollback
            assert len(rollback_calls) == 2
            assert rollback_calls[1]["updates"]["current_stage"] == "IDEA_REVIEW"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 9. Race: worker claims before promote doesn't clobber
# ---------------------------------------------------------------------------


class TestPromoteRaceCondition:
    """Atomic promote must not clobber a concurrent claim_running."""

    def test_promote_after_claim_running_returns_none(self) -> None:
        """If worker claims (pending→running) before promote, promote returns None."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            # Record pending
            task = await service.record_task_pending(1, "generate_script", "celery-race-promote")
            # Worker claims it immediately (pending→running)
            row = await storage.get_by_celery_id("celery-race-promote")
            assert row is not None
            claimed = await storage.claim_running(row["id"], started_at=datetime.now(timezone.utc))
            assert claimed is not None
            assert claimed["status"] == "running"

            # Now promote — should return None, NOT clobber running→queued
            promoted = await service.promote_pending_to_queued("celery-race-promote")
            assert promoted is None

            # Verify task is still running
            final = await storage.get_by_celery_id("celery-race-promote")
            assert final is not None
            assert final["status"] == "running"

        asyncio.run(_run())

    def test_promote_uses_atomic_storage_method(self) -> None:
        """Service.promote_pending_to_queued must delegate to storage.promote_pending_to_queued,
        NOT use the read-then-update pattern (get_by_celery_id + update_task_status)."""

        class _SpyStorage:
            """Storage that only exposes promote_pending_to_queued; raises on TOCTOU methods."""

            promote_called = False

            async def promote_pending_to_queued(self, celery_task_id: str) -> dict[str, Any] | None:
                self.promote_called = True
                return {
                    "id": 1, "run_id": 1, "task_type": "generate_script",
                    "celery_task_id": celery_task_id, "status": "queued",
                    "attempt": 1, "created_at": datetime.now(timezone.utc),
                    "started_at": None, "finished_at": None,
                    "error_code": None, "error_message": None,
                }

            async def get_by_celery_id(self, celery_task_id: str) -> dict[str, Any] | None:
                raise AssertionError("promote should NOT call get_by_celery_id (TOCTOU)")

            async def update_task_status(self, task_id: int, status: str, **kw: Any) -> dict[str, Any] | None:
                raise AssertionError("promote should NOT call update_task_status (TOCTOU)")

            # Stubs for Protocol compliance (unused in this test)
            async def create_task(self, row: dict[str, Any]) -> dict[str, Any] | None:
                return None
            async def claim_running(self, task_id: int, **kw: Any) -> dict[str, Any] | None:
                return None
            async def list_by_run(self, run_id: int) -> list[dict[str, Any]]:
                return []
            async def list_stuck_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]:
                return []
            async def list_stale_pending_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]:
                return []
            async def get_active_celery_ids(self, run_id: int) -> list[str]:
                return []

        spy = _SpyStorage()
        service = TaskTrackingService(spy)  # type: ignore[arg-type]

        async def _run() -> None:
            result = await service.promote_pending_to_queued("celery-spy")
            assert result is not None
            assert result.status == "queued"
            assert spy.promote_called

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 10. Duplicate reconciler run is idempotent
# ---------------------------------------------------------------------------


class TestReconcilerIdempotency:
    """Running reconciler twice should not duplicate work."""

    def test_second_reconciler_pass_finds_nothing(self) -> None:
        """After first pass promotes pending→queued, second pass has nothing to do."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)
        enqueue_count = 0

        async def _run() -> None:
            nonlocal enqueue_count
            from creator_service.dispatch_reconciler import DispatchReconciler

            # Create stale pending task
            await storage.create_task({
                "run_id": 1,
                "task_type": "generate_script",
                "celery_task_id": "celery-idem-1",
                "status": "pending",
                "attempt": 1,
                "created_at": datetime.now(timezone.utc) - timedelta(seconds=300),
            })

            async def fake_enqueue(celery_task_id: str, task_type: str, run_id: int) -> bool:
                nonlocal enqueue_count
                enqueue_count += 1
                return True

            reconciler = DispatchReconciler(
                task_tracking_service=service,
                enqueue_fn=fake_enqueue,
                threshold_seconds=60,
            )

            # First pass: should re-enqueue
            r1 = await reconciler.reconcile()
            assert r1.reenqueued == 1

            # Second pass: task is now 'queued', should find nothing
            r2 = await reconciler.reconcile()
            assert r2.reenqueued == 0
            assert r2.rolled_back == 0
            assert enqueue_count == 1  # Only called once total

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 11. Postgres storage: promote_pending_to_queued method
# ---------------------------------------------------------------------------


class TestPostgresPromotePendingToQueued:
    """Postgres storage must have atomic promote_pending_to_queued."""

    def test_promote_pending_to_queued_sql_uses_where_pending(self) -> None:
        """SQL must include WHERE status = 'pending' for atomicity."""
        import inspect
        from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage

        source = inspect.getsource(PostgresTaskTrackingStorage.promote_pending_to_queued)
        assert "status = 'pending'" in source, (
            "promote_pending_to_queued SQL must filter WHERE status = 'pending'"
        )

    def test_promote_pending_to_queued_sets_status_queued(self) -> None:
        """SQL must SET status = 'queued'."""
        import inspect
        from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage

        source = inspect.getsource(PostgresTaskTrackingStorage.promote_pending_to_queued)
        assert "SET status = 'queued'" in source


# ---------------------------------------------------------------------------
# 12. Integration: periodic reconciler rolls back stale tasks
# ---------------------------------------------------------------------------


class TestPeriodicReconcilerIntegration:
    """Integration test proving the periodic reconciler wiring rolls back stale tasks."""

    def test_stale_pending_task_gets_rolled_back_and_marked_failed(self) -> None:
        """Full reconciler flow: stale pending → enqueue fails → rollback_fn called → task marked failed."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)
        rolled_back_runs: list[tuple[int, str]] = []

        async def _run() -> None:
            from creator_service.dispatch_reconciler import DispatchReconciler

            # Create stale pending task (old enough to be reconciled)
            await storage.create_task({
                "run_id": 42,
                "task_type": "generate_script",
                "celery_task_id": "celery-stale-integration",
                "status": "pending",
                "attempt": 1,
                "created_at": datetime.now(timezone.utc) - timedelta(seconds=300),
            })

            # Enqueue always fails (can't reconstruct original args)
            async def fail_enqueue(celery_task_id: str, task_type: str, run_id: int) -> bool:
                return False

            # Rollback records the run_id and task_id
            async def rollback_fn(run_id: int, celery_task_id: str) -> None:
                rolled_back_runs.append((run_id, celery_task_id))

            reconciler = DispatchReconciler(
                task_tracking_service=service,
                enqueue_fn=fail_enqueue,
                rollback_fn=rollback_fn,
                threshold_seconds=60,
            )
            result = await reconciler.reconcile()

            # Verify rollback was called
            assert result.rolled_back == 1
            assert result.reenqueued == 0
            assert len(rolled_back_runs) == 1
            assert rolled_back_runs[0] == (42, "celery-stale-integration")

            # Verify task was marked failed (not still pending)
            task_row = await storage.get_by_celery_id("celery-stale-integration")
            assert task_row is not None
            assert task_row["status"] == "failed"
            assert task_row["error_code"] == "reconciler_rollback"

            # Second reconcile pass should find nothing
            result2 = await reconciler.reconcile()
            assert result2.rolled_back == 0
            assert result2.reenqueued == 0

        asyncio.run(_run())

    def test_reconciler_without_rollback_fn_still_marks_task_failed(self) -> None:
        """Even without rollback_fn, task should be marked failed to prevent retry loops."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        async def _run() -> None:
            from creator_service.dispatch_reconciler import DispatchReconciler

            await storage.create_task({
                "run_id": 99,
                "task_type": "generate_audio",
                "celery_task_id": "celery-no-rollback",
                "status": "pending",
                "attempt": 1,
                "created_at": datetime.now(timezone.utc) - timedelta(seconds=300),
            })

            async def fail_enqueue(celery_task_id: str, task_type: str, run_id: int) -> bool:
                return False

            # No rollback_fn provided
            reconciler = DispatchReconciler(
                task_tracking_service=service,
                enqueue_fn=fail_enqueue,
                rollback_fn=None,
                threshold_seconds=60,
            )
            result = await reconciler.reconcile()
            assert result.rolled_back == 1

            # Task still marked failed even without rollback_fn
            task_row = await storage.get_by_celery_id("celery-no-rollback")
            assert task_row is not None
            assert task_row["status"] == "failed"

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# 13. Reconciler must NOT clobber a run that has already advanced
# ---------------------------------------------------------------------------


class TestReconcilerDoesNotClobberAdvancedRun:
    """Stale pending task reconciliation must not reset a run that already advanced."""

    def test_rollback_skips_run_already_in_terminal_stage(self) -> None:
        """If user retried and run is now COMPLETED, reconciler must NOT reset to FAILED."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)

        # Track rollback calls and their conditional behavior
        rollback_conditional_results: list[tuple[int, bool]] = []

        async def _run() -> None:
            from creator_service.dispatch_reconciler import DispatchReconciler

            # Create stale pending task
            await storage.create_task({
                "run_id": 100,
                "task_type": "generate_script",
                "celery_task_id": "celery-already-advanced",
                "status": "pending",
                "attempt": 1,
                "created_at": datetime.now(timezone.utc) - timedelta(seconds=300),
            })

            async def fail_enqueue(celery_task_id: str, task_type: str, run_id: int) -> bool:
                return False

            # Simulate a run that has already been retried and completed.
            # The rollback_fn uses conditional_update_run which should be
            # a no-op when the run is in a terminal stage.
            class _FakeRunStorage:
                """Simulates conditional_update_run rejecting because run already advanced."""
                async def conditional_update_run(
                    self, run_id, updates, *, expected_stages, rejected_statuses=None, workspace_id=None
                ):
                    # Run is at COMPLETED — not in expected_stages, so reject
                    rollback_conditional_results.append((run_id, False))
                    return False, {"current_stage": "COMPLETED", "status": "completed"}

            class _FakeRunService:
                storage = _FakeRunStorage()

            # Use the real _rollback_run from the reconciler module
            import sys
            sys.path.insert(0, "apps/worker-orchestrator")
            from tasks.reconcile_stale_dispatches import _rollback_run

            reconciler = DispatchReconciler(
                task_tracking_service=service,
                enqueue_fn=fail_enqueue,
                rollback_fn=_rollback_run,
                threshold_seconds=60,
            )

            # Monkey-patch run_service for this test
            from unittest.mock import patch, MagicMock
            fake_module = MagicMock()
            fake_module.run_service = _FakeRunService()

            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "creator_service.run_service":
                        return fake_module
                    return __import__("importlib").import_module(name)
                mock_import.side_effect = side_effect

                result = await reconciler.reconcile()

            # Task should still be marked failed (cleaned up)
            assert result.rolled_back == 1
            assert result.errors == []  # No errors — rollback was a safe no-op

            # conditional_update_run was called and returned False (no clobber)
            assert len(rollback_conditional_results) == 1
            assert rollback_conditional_results[0] == (100, False)

            # Task is marked failed so it won't be retried
            task_row = await storage.get_by_celery_id("celery-already-advanced")
            assert task_row is not None
            assert task_row["status"] == "failed"

        asyncio.run(_run())

    def test_rollback_succeeds_for_stuck_generating_run(self) -> None:
        """If run is still in SCRIPT_GENERATING (stuck), reconciler SHOULD roll it back."""
        storage = InMemoryTaskTrackingStorage()
        service = TaskTrackingService(storage)
        rollback_applied: list[int] = []

        async def _run() -> None:
            from creator_service.dispatch_reconciler import DispatchReconciler

            await storage.create_task({
                "run_id": 101,
                "task_type": "generate_script",
                "celery_task_id": "celery-stuck-generating",
                "status": "pending",
                "attempt": 1,
                "created_at": datetime.now(timezone.utc) - timedelta(seconds=300),
            })

            async def fail_enqueue(celery_task_id: str, task_type: str, run_id: int) -> bool:
                return False

            class _FakeRunStorage:
                async def conditional_update_run(
                    self, run_id, updates, *, expected_stages, rejected_statuses=None, workspace_id=None
                ):
                    # Run is at SCRIPT_GENERATING — in expected_stages, so accept
                    assert "SCRIPT_GENERATING" in expected_stages
                    rollback_applied.append(run_id)
                    return True, {"current_stage": "FAILED", "status": "failed"}

            class _FakeRunService:
                storage = _FakeRunStorage()

            import sys
            if "apps/worker-orchestrator" not in sys.path:
                sys.path.insert(0, "apps/worker-orchestrator")
            from tasks.reconcile_stale_dispatches import _rollback_run

            reconciler = DispatchReconciler(
                task_tracking_service=service,
                enqueue_fn=fail_enqueue,
                rollback_fn=_rollback_run,
                threshold_seconds=60,
            )

            from unittest.mock import patch, MagicMock
            fake_module = MagicMock()
            fake_module.run_service = _FakeRunService()

            with patch("importlib.import_module") as mock_import:
                def side_effect(name):
                    if name == "creator_service.run_service":
                        return fake_module
                    return __import__("importlib").import_module(name)
                mock_import.side_effect = side_effect

                result = await reconciler.reconcile()

            assert result.rolled_back == 1
            assert result.errors == []
            assert rollback_applied == [101]

        asyncio.run(_run())
