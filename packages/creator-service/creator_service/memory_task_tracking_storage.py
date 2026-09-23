from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


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

    async def update_task_status_if_running(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        """Only transition if current status is running (true CAS guard)."""
        row = self._rows.get(task_id)
        if row is None:
            return None
        if row.get("status") != "running":
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
