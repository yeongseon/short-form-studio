# pyright: reportMissingImports=false
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models import RunTask


class TaskTrackingStorageBackend(Protocol):
    async def create_task(self, row: dict[str, Any]) -> dict[str, Any] | None: ...

    async def update_task_status(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None: ...

    async def get_by_celery_id(self, celery_task_id: str) -> dict[str, Any] | None: ...

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]: ...

    async def claim_running(self, task_id: int, **kwargs: Any) -> dict[str, Any] | None: ...

    async def list_stuck_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]: ...

    async def list_stale_pending_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]: ...

    async def promote_pending_to_queued(self, celery_task_id: str) -> dict[str, Any] | None: ...

    async def get_active_celery_ids(self, run_id: int) -> list[str]: ...


class InMemoryTaskTrackingStorage:
    def __init__(self) -> None:
        self._rows: dict[int, dict[str, Any]] = {}
        self._rows_by_celery_task_id: dict[str, int] = {}
        self._next_id = 1

    async def create_task(self, row: dict[str, Any]) -> dict[str, Any] | None:
        celery_task_id = row.get("celery_task_id")
        if isinstance(celery_task_id, str):
            existing_id = self._rows_by_celery_task_id.get(celery_task_id)
            if existing_id is not None:
                existing = self._rows[existing_id]
                current_status = existing.get("status")
                if current_status in ("success", "running"):
                    return None
                incoming_status = row.get("status", "queued")
                existing["status"] = incoming_status
                if incoming_status == "queued":
                    existing["attempt"] = int(existing.get("attempt", 0)) + 1
                    existing["started_at"] = None
                    existing["finished_at"] = None
                    existing["error_code"] = None
                    existing["error_message"] = None
                elif incoming_status == "running":
                    existing["started_at"] = row.get("started_at")
                    existing["finished_at"] = None
                    existing["error_code"] = None
                    existing["error_message"] = None
                self._rows[existing_id] = existing
                return dict(existing)

        now = datetime.now(timezone.utc)
        saved = {
            "id": self._next_id,
            "created_at": now,
            "status": "queued",
            "attempt": 1,
            "started_at": None,
            "finished_at": None,
            "error_code": None,
            "error_message": None,
            **row,
        }
        self._rows[self._next_id] = saved
        if isinstance(celery_task_id, str):
            self._rows_by_celery_task_id[celery_task_id] = self._next_id
        self._next_id += 1
        return dict(saved)

    async def update_task_status(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        row = self._rows.get(task_id)
        if row is None:
            return None
        current_status = row.get("status")
        if current_status == "success":
            return None
        if status == "running" and current_status == "running":
            return None
        row["status"] = status
        if "started_at" in kwargs:
            row["started_at"] = kwargs["started_at"]
        if "finished_at" in kwargs:
            row["finished_at"] = kwargs["finished_at"]
        if kwargs.get("attempt") is not None:
            row["attempt"] = kwargs["attempt"]
        row["error_code"] = kwargs.get("error_code")
        row["error_message"] = kwargs.get("error_message")
        self._rows[task_id] = row
        return dict(row)

    async def claim_running(self, task_id: int, **kwargs: Any) -> dict[str, Any] | None:
        """Atomically claim a task: only transition from pending/queued/failed to running."""
        row = self._rows.get(task_id)
        if row is None:
            return None
        if row.get("status") not in ("pending", "queued", "failed"):
            return None
        row["status"] = "running"
        if "started_at" in kwargs:
            row["started_at"] = kwargs["started_at"]
        row["finished_at"] = None
        row["error_code"] = None
        row["error_message"] = None
        if kwargs.get("attempt") is not None:
            row["attempt"] = kwargs["attempt"]
        self._rows[task_id] = row
        return dict(row)

    async def get_by_celery_id(self, celery_task_id: str) -> dict[str, Any] | None:
        for row in self._rows.values():
            if row.get("celery_task_id") == celery_task_id:
                return dict(row)
        return None

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self._rows.values() if row.get("run_id") == run_id]
        rows.sort(key=lambda row: row.get("id", 0), reverse=True)
        return rows

    async def list_stuck_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc).timestamp() - threshold_seconds
        stuck: list[dict[str, Any]] = []
        for row in self._rows.values():
            if row.get("status") != "running":
                continue
            started_at = row.get("started_at")
            if started_at is None:
                continue
            if started_at.timestamp() < cutoff:
                stuck.append(dict(row))
        stuck.sort(
            key=lambda row: row.get("started_at") or datetime.min.replace(tzinfo=timezone.utc)
        )
        return stuck

    async def list_stale_pending_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]:
        """Find tasks stuck in 'pending' state longer than threshold_seconds."""
        cutoff = datetime.now(timezone.utc).timestamp() - threshold_seconds
        stale: list[dict[str, Any]] = []
        for row in self._rows.values():
            if row.get("status") != "pending":
                continue
            created_at = row.get("created_at")
            if created_at is None:
                continue
            if created_at.timestamp() < cutoff:
                stale.append(dict(row))
        stale.sort(
            key=lambda row: row.get("created_at") or datetime.min.replace(tzinfo=timezone.utc)
        )
        return stale

    async def promote_pending_to_queued(self, celery_task_id: str) -> dict[str, Any] | None:
        """Atomically promote a task from 'pending' to 'queued'. Returns None if not pending."""
        row_id = self._rows_by_celery_task_id.get(celery_task_id)
        if row_id is None:
            # Fallback: search by celery_task_id
            for rid, row in self._rows.items():
                if row.get("celery_task_id") == celery_task_id:
                    row_id = rid
                    break
        if row_id is None:
            return None
        row = self._rows.get(row_id)
        if row is None or row.get("status") != "pending":
            return None
        row["status"] = "queued"
        self._rows[row_id] = row
        return dict(row)

    async def get_active_celery_ids(self, run_id: int) -> list[str]:
        return [
            row["celery_task_id"]
            for row in self._rows.values()
            if row.get("run_id") == run_id
            and row.get("status") in ("queued", "pending", "running")
            and row.get("celery_task_id")
        ]


class TaskTrackingService:
    def __init__(self, storage: TaskTrackingStorageBackend):
        self.storage = storage

    async def record_task_pending(
        self, run_id: int, task_type: str, celery_task_id: str
    ) -> RunTask:
        """Record a task as 'pending' before broker enqueue.

        This is the first step of the atomic dispatch pattern:
        1. Record task as 'pending' (this method)
        2. Enqueue to broker
        3. Promote to 'queued' via promote_pending_to_queued()

        Raises ValueError if the task already exists in a non-retriable state
        (running, success).
        """
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

    async def promote_pending_to_queued(self, celery_task_id: str) -> RunTask | None:
        """Atomically promote a pending task to queued after successful broker enqueue.

        Uses a CAS operation in storage to avoid TOCTOU race with claim_running.
        Returns None if the task is no longer pending (e.g. worker already
        claimed it via claim_running).
        """
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

    async def record_task_start(self, run_id: int, task_type: str, celery_task_id: str) -> RunTask | None:
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
            if status == "running":
                # Already claimed by another worker — do not execute
                return None
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
        )
        if row is None:
            # Concurrent claim or task already succeeded — cannot claim
            return None
        return RunTask.from_row(row)

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

    async def list_run_tasks(self, run_id: int) -> list[RunTask]:
        rows = await self.storage.list_by_run(run_id)
        return [RunTask.from_row(row) for row in rows]

    async def find_stuck_tasks(self, threshold_seconds: int = 600) -> list[RunTask]:
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


def _create_storage() -> TaskTrackingStorageBackend:
    if os.getenv("DATABASE_URL"):
        from .postgres_task_tracking_storage import PostgresTaskTrackingStorage

        return PostgresTaskTrackingStorage()
    return InMemoryTaskTrackingStorage()


task_tracking_service = TaskTrackingService(_create_storage())
