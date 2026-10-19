# pyright: reportMissingImports=false
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .run_service import RunStorageBackend
    from .usage_service import UsageStorageBackend

from creator_domain.models import RunTask

from .memory_task_tracking_storage import InMemoryTaskTrackingStorage as InMemoryTaskTrackingStorage
from .task_tracking_storage import BillingOutcome, TaskTrackingStorageBackend, create_task_tracking_storage


class TaskTrackingService:
    def __init__(self, storage: TaskTrackingStorageBackend):
        self.storage = storage

    async def record_task_pending(
        self, run_id: int, task_type: str, celery_task_id: str
    ) -> RunTask:
        """Record the durable pending state before broker enqueue."""
        row = await self.storage.create_task(
            {
                "run_id": run_id,
                "task_type": task_type,
                "celery_task_id": celery_task_id,
                "status": "pending",
                "attempt": 1,
            }
        )
        if row is None:
            raise ValueError(
                f"Failed to record pending task {celery_task_id}: "
                "task is already running or succeeded"
            )
        return RunTask.from_row(row)

    async def transition_run_and_record_pending(
        self, run_storage: RunStorageBackend, run_id: int, updates: dict[str, Any],
        expected_stages: frozenset[str], task_type: str, celery_task_id: str,
        *, workspace_id: int | None = None,
        rejected_statuses: frozenset[str] = frozenset(),
    ) -> tuple[bool, dict[str, Any] | None]:
        return await self.storage.transition_run_and_create_pending(
            run_storage,
            run_id,
            updates,
            expected_stages,
            {
                "run_id": run_id,
                "task_type": task_type,
                "celery_task_id": celery_task_id,
                "status": "pending",
                "attempt": 1,
            },
            workspace_id,
            rejected_statuses,
        )

    async def promote_pending_to_queued(self, celery_task_id: str) -> RunTask | None:
        """Promote pending to queued without overwriting a worker claim."""
        row = await self.storage.promote_pending_to_queued(celery_task_id)
        return RunTask.from_row(row) if row is not None else None

    async def record_task_queued(self, run_id: int, task_type: str, celery_task_id: str) -> RunTask:
        row = await self.storage.create_task(
            {
                "run_id": run_id,
                "task_type": task_type,
                "celery_task_id": celery_task_id,
                "status": "queued",
                "attempt": 1,
            }
        )
        if row is None:
            raise ValueError(f"Failed to queue task {celery_task_id}: task is already running or succeeded")
        return RunTask.from_row(row)

    async def record_task_start(
        self, run_id: int, task_type: str, celery_task_id: str, *, claim_token: str | None = None,
    ) -> RunTask | None:
        """Attempt to exclusively claim a task for execution.

        Returns:
            RunTask with status="running" if claim succeeded.
            RunTask with status="success" if task already completed (caller should skip).
            None if task is already claimed by another worker (caller should skip).
        """
        existing = await self.storage.get_by_celery_id(celery_task_id)
        if existing is not None:
            status = existing.get("status")
            if status == "success":
                return RunTask.from_row(existing)
        started_at = datetime.now(timezone.utc)
        if existing is None:
            row = await self.storage.create_task(
                {
                    "run_id": run_id,
                    "task_type": task_type,
                    "celery_task_id": celery_task_id,
                    "status": "running",
                    "attempt": 1,
                    "started_at": started_at,
                    "finished_at": None,
                    "error_code": None,
                    "error_message": None,
                    "claim_token": claim_token,
                }
            )
            if row is None:
                # Concurrent insert claimed it first (Postgres ON CONFLICT returned nothing)
                return None
            return RunTask.from_row(row)

        attempt = int(existing.get("attempt", 1))

        row = await self.storage.claim_running(
            existing["id"],
            attempt=attempt,
            started_at=started_at,
            claim_token=claim_token,
            expected_claim_token=existing.get("claim_token"),
        )
        if row is None:
            # Concurrent claim or task already succeeded — cannot claim
            return None
        return RunTask.from_row(row)

    async def mark_failed_if_claimed(
        self, celery_task_id: str, token: str, code: str, message: str,
    ) -> RunTask | None:
        row = await self.storage.finish_if_claimed(celery_task_id, token, "failed", code, message)
        return RunTask.from_row(row) if row is not None else None

    async def mark_success_if_claimed(self, celery_task_id: str, token: str) -> RunTask | None:
        row = await self.storage.finish_if_claimed(celery_task_id, token, "success")
        return RunTask.from_row(row) if row is not None else None

    async def mark_rejected_if_claimed(self, celery_task_id: str, token: str) -> RunTask | None:
        row = await self.storage.finish_if_claimed(
            celery_task_id, token, "rejected", "rejected", "stage_guard",
        )
        return RunTask.from_row(row) if row is not None else None

    async def finish_claimed_run(
        self, celery_task_id: str, token: str, status: str, run_storage: RunStorageBackend,
        run_id: int, run_updates: dict[str, str], expected_stages: frozenset[str],
        rejected_statuses: frozenset[str], error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        return await self.storage.finish_claimed_run(
            celery_task_id, token, status, run_storage, run_id,
            run_updates, expected_stages, rejected_statuses, error_code, error_message,
        )

    async def fail_claimed_and_cancel_quota(
        self, celery_task_id: str, token: str, usage_storage: UsageStorageBackend,
        error_code: str, error_message: str, run_storage: RunStorageBackend | None = None,
        run_id: int | None = None, expected_stages: frozenset[str] = frozenset(),
        billing_outcome: BillingOutcome | None = None,
    ) -> bool:
        return await self.storage.fail_claimed_and_cancel_quota(
            celery_task_id, token, usage_storage, error_code, error_message,
            run_storage, run_id, expected_stages, billing_outcome,
        )

    async def mark_running(self, celery_task_id: str) -> RunTask | None:
        task = await self.storage.get_by_celery_id(celery_task_id)
        if task is None:
            return None
        row = await self.storage.update_task_status(
            task["id"],
            "running",
            started_at=datetime.now(timezone.utc),
            error_code=None,
            error_message=None,
        )
        return RunTask.from_row(row) if row is not None else None

    async def mark_success(self, celery_task_id: str) -> RunTask | None:
        task = await self.storage.get_by_celery_id(celery_task_id)
        if task is None:
            return None
        row = await self.storage.update_task_status(
            task["id"],
            "success",
            finished_at=datetime.now(timezone.utc),
            error_code=None,
            error_message=None,
        )
        return RunTask.from_row(row) if row is not None else None

    async def mark_success_if_running(self, celery_task_id: str) -> RunTask | None:
        task = await self.storage.get_by_celery_id(celery_task_id)
        if task is None:
            return None
        row = await self.storage.update_task_status_if_running(
            task["id"],
            "success",
            finished_at=datetime.now(timezone.utc),
            error_code=None,
            error_message=None,
        )
        return RunTask.from_row(row) if row is not None else None

    async def mark_failed(
        self, celery_task_id: str, error_code: str, error_message: str
    ) -> RunTask | None:
        task = await self.storage.get_by_celery_id(celery_task_id)
        if task is None:
            return None
        row = await self.storage.update_task_status(
            task["id"],
            "failed",
            finished_at=datetime.now(timezone.utc),
            error_code=error_code,
            error_message=error_message,
        )
        return RunTask.from_row(row) if row is not None else None

    async def mark_failed_if_running(
        self, celery_task_id: str, error_code: str, error_message: str
    ) -> RunTask | None:
        """Mark task as failed ONLY if currently in running state (true CAS guard).

        Unlike mark_failed(), this will NOT overwrite revoked/rejected states.
        Returns None if the task was not in running state (CAS miss).
        """
        task = await self.storage.get_by_celery_id(celery_task_id)
        if task is None:
            return None
        row = await self.storage.update_task_status_if_running(
            task["id"],
            "failed",
            finished_at=datetime.now(timezone.utc),
            error_code=error_code,
            error_message=error_message,
        )
        return RunTask.from_row(row) if row is not None else None

    async def mark_failed_if_pending(
        self, celery_task_id: str, error_code: str, error_message: str
    ) -> RunTask | None:
        task = await self.storage.get_by_celery_id(celery_task_id)
        if task is None:
            return None
        row = await self.storage.update_task_status_if_pending(
            task["id"],
            "failed",
            finished_at=datetime.now(timezone.utc),
            error_code=error_code,
            error_message=error_message,
        )
        return RunTask.from_row(row) if row is not None else None

    async def mark_revoked(self, celery_task_id: str) -> RunTask | None:
        """Called externally by admin API or monitoring tools when a task is manually revoked."""
        task = await self.storage.get_by_celery_id(celery_task_id)
        if task is None:
            return None
        row = await self.storage.update_task_status(
            task["id"],
            "revoked",
            finished_at=datetime.now(timezone.utc),
        )
        return RunTask.from_row(row) if row is not None else None

    async def mark_rejected(
        self, celery_task_id: str, reason: str = "stage_guard"
    ) -> RunTask | None:
        """Mark a task as rejected when it cannot proceed (e.g. stage guard failure).

        This prevents tasks from remaining stuck as 'running' when they are
        rejected before doing real work.
        """
        task = await self.storage.get_by_celery_id(celery_task_id)
        if task is None:
            return None
        row = await self.storage.update_task_status(
            task["id"],
            "rejected",
            finished_at=datetime.now(timezone.utc),
            error_code="rejected",
            error_message=reason,
        )
        return RunTask.from_row(row) if row is not None else None

    async def find_stale_pending_tasks(self, threshold_seconds: int = 120) -> list[RunTask]:
        """Find tasks stuck in 'pending' state beyond threshold."""
        rows = await self.storage.list_stale_pending_tasks(threshold_seconds)
        return [RunTask.from_row(row) for row in rows]

    async def find_reconciliation_pending_tasks(
        self, lease_seconds: int = 300
    ) -> list[RunTask]:
        rows = await self.storage.list_reconciliation_pending_tasks(lease_seconds)
        return [RunTask.from_row(row) for row in rows]

    async def claim_reconciliation(
        self, task_id: int, claim_token: str, lease_seconds: int = 300
    ) -> RunTask | None:
        row = await self.storage.claim_reconciliation(task_id, claim_token, lease_seconds)
        return RunTask.from_row(row) if row is not None else None

    async def finish_reconciliation(
        self, celery_task_id: str, claim_token: str, error_code: str, error_message: str
    ) -> RunTask | None:
        row = await self.storage.finish_reconciliation(
            celery_task_id, claim_token, error_code, error_message
        )
        return RunTask.from_row(row) if row is not None else None

    async def release_reconciliation(
        self, celery_task_id: str, claim_token: str
    ) -> RunTask | None:
        row = await self.storage.release_reconciliation(celery_task_id, claim_token)
        return RunTask.from_row(row) if row is not None else None

    async def rollback_run_if_task_owner(
        self, celery_task_id: str, run_storage: RunStorageBackend,
        run_id: int, eligible_task_types: frozenset[str],
        expected_stages: frozenset[str], rejected_statuses: frozenset[str],
    ) -> tuple[bool, dict[str, Any] | None]:
        return await self.storage.rollback_run_if_task_owner(
            celery_task_id, run_storage, run_id, eligible_task_types,
            expected_stages, rejected_statuses,
        )

    async def list_run_tasks(self, run_id: int) -> list[RunTask]:
        rows = await self.storage.list_by_run(run_id)
        return [RunTask.from_row(row) for row in rows]

    async def find_stuck_tasks(self, threshold_seconds: int = 900) -> list[RunTask]:
        rows = await self.storage.list_stuck_tasks(threshold_seconds)
        return [RunTask.from_row(row) for row in rows]

    async def get_active_celery_ids(self, run_id: int) -> list[str]:
        return await self.storage.get_active_celery_ids(run_id)

    async def has_active_tasks(self, run_id: int) -> bool:
        ids = await self.get_active_celery_ids(run_id)
        return len(ids) > 0

    async def revoke_active_tasks(self, run_id: int) -> list[str]:
        return await self.get_active_celery_ids(run_id)

    async def mark_tasks_revoked(self, celery_ids: list[str]) -> None:
        for celery_id in celery_ids:
            await self.mark_revoked(celery_id)


task_tracking_service = TaskTrackingService(create_task_tracking_storage())
