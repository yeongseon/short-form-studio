# pyright: reportMissingImports=false
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models import RunTask


class TaskTrackingStorageBackend(Protocol):
    async def create_task(self, row: dict[str, Any]) -> dict[str, Any]: ...

    async def update_task_status(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None: ...

    async def get_by_celery_id(self, celery_task_id: str) -> dict[str, Any] | None: ...

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]: ...

    async def list_stuck_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]: ...


class InMemoryTaskTrackingStorage:
    def __init__(self) -> None:
        self._rows: dict[int, dict[str, Any]] = {}
        self._rows_by_celery_task_id: dict[str, int] = {}
        self._next_id = 1

    async def create_task(self, row: dict[str, Any]) -> dict[str, Any]:
        celery_task_id = row.get("celery_task_id")
        if isinstance(celery_task_id, str):
            existing_id = self._rows_by_celery_task_id.get(celery_task_id)
            if existing_id is not None:
                existing = self._rows[existing_id]
                existing["status"] = "running"
                existing["attempt"] = int(existing.get("attempt", 0)) + 1
                existing["started_at"] = datetime.now(timezone.utc)
                existing["error_code"] = None
                existing["error_message"] = None
                self._rows[existing_id] = existing
                return dict(existing)

        now = datetime.now(timezone.utc)
        saved = {
            "id": self._next_id,
            "created_at": now,
            "status": "pending",
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
        row["status"] = status
        if kwargs.get("started_at") is not None:
            row["started_at"] = kwargs["started_at"]
        if kwargs.get("finished_at") is not None:
            row["finished_at"] = kwargs["finished_at"]
        row["error_code"] = kwargs.get("error_code")
        row["error_message"] = kwargs.get("error_message")
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


class TaskTrackingService:
    def __init__(self, storage: TaskTrackingStorageBackend):
        self.storage = storage

    async def record_task_start(self, run_id: int, task_type: str, celery_task_id: str) -> RunTask:
        row = await self.storage.create_task(
            {
                "run_id": run_id,
                "task_type": task_type,
                "celery_task_id": celery_task_id,
                "status": "pending",
                "attempt": 1,
            }
        )
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

    async def list_run_tasks(self, run_id: int) -> list[RunTask]:
        rows = await self.storage.list_by_run(run_id)
        return [RunTask.from_row(row) for row in rows]

    async def find_stuck_tasks(self, threshold_seconds: int = 600) -> list[RunTask]:
        rows = await self.storage.list_stuck_tasks(threshold_seconds)
        return [RunTask.from_row(row) for row in rows]


def _create_storage() -> TaskTrackingStorageBackend:
    if os.getenv("DATABASE_URL"):
        from .postgres_task_tracking_storage import PostgresTaskTrackingStorage

        return PostgresTaskTrackingStorage()
    return InMemoryTaskTrackingStorage()


task_tracking_service = TaskTrackingService(_create_storage())
