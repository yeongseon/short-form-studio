from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, assert_never

import anyio

if TYPE_CHECKING:
    from .run_service import InMemoryRunStorage
    from .usage_service import InMemoryUsageStorage

from .task_tracking_storage import BillingOutcome


class InMemoryTaskTrackingStorage:
    def __init__(self) -> None:
        self._rows: dict[int, dict[str, Any]] = {}
        self._rows_by_celery_task_id: dict[str, int] = {}
        self._next_id = 1
        self._observed_broker_epoch: str | None = None
        self._ownership_lock = anyio.Lock()

    async def transition_run_and_create_pending(
        self, run_storage: InMemoryRunStorage, run_id: int, updates: dict[str, Any],
        expected_stages: frozenset[str], task_row: dict[str, Any],
        workspace_id: int | None, rejected_statuses: frozenset[str],
    ) -> tuple[bool, dict[str, Any] | None]:
        async with self._ownership_lock:
            previous = await run_storage.get_run(run_id, workspace_id)
            ok, row = await run_storage.conditional_update_run(
                run_id, updates, expected_stages, workspace_id, rejected_statuses
            )
            if not ok:
                return False, row
            committed = False
            try:
                pending = await self.create_task(task_row)
                if pending is None:
                    raise ValueError("Pending task ownership already exists")
                committed = True
            finally:
                if not committed and previous is not None:
                    run_storage._rows[run_id] = previous
            return True, row

    async def create_task(self, row: dict[str, Any]) -> dict[str, Any] | None:
        celery_task_id = row.get("celery_task_id")
        if isinstance(celery_task_id, str):
            existing_id = self._rows_by_celery_task_id.get(celery_task_id)
            if existing_id is not None:
                existing = self._rows[existing_id]
                current_status = existing.get("status")
                if current_status in ("success", "running") or existing.get("error_code") in {
                    "reconciler_pending_cleanup",
                    "reconciler_stuck_cleanup",
                    "reconciler_cleanup_claimed",
                    "broker_recovery_cleanup",
                    "broker_message_lost",
                }:
                    return None
                incoming_status = row.get("status", "queued")
                existing["status"] = incoming_status
                if incoming_status == "queued":
                    existing["claim_token"] = None
                    existing["attempt"] = int(existing.get("attempt", 0)) + 1
                    existing["started_at"] = None
                    existing["finished_at"] = None
                    existing["error_code"] = None
                    existing["error_message"] = None
                elif incoming_status == "running":
                    existing["claim_token"] = row.get("claim_token")
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
            "claim_token": None,
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

    async def update_task_status_if_pending(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        row = self._rows.get(task_id)
        if row is None or row.get("status") != "pending":
            return None
        row["status"] = status
        row["finished_at"] = kwargs.get("finished_at")
        row["error_code"] = kwargs.get("error_code")
        row["error_message"] = kwargs.get("error_message")
        return dict(row)

    async def update_task_status_if_active(
        self, celery_task_id: str, status: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        row_id = self._rows_by_celery_task_id.get(celery_task_id)
        if row_id is None:
            return None
        row = self._rows[row_id]
        if row.get("status") not in ("pending", "queued", "running"):
            return None
        row.update(
            status=status,
            finished_at=kwargs.get("finished_at"),
            error_code=kwargs.get("error_code"),
            error_message=kwargs.get("error_message"),
            claim_token=None,
        )
        return dict(row)

    async def finish_if_claimed(
        self, celery_task_id: str, token: str, status: str,
        error_code: str | None = None, error_message: str | None = None,
    ) -> dict[str, Any] | None:
        row_id = self._rows_by_celery_task_id.get(celery_task_id)
        if row_id is None:
            return None
        row = self._rows[row_id]
        if row.get("status") != "running" or row.get("claim_token") != token:
            return None
        row.update(status=status, claim_token=None, finished_at=datetime.now(timezone.utc),
                   error_code=error_code, error_message=error_message)
        return dict(row)

    async def finish_claimed_run(
        self, celery_task_id: str, token: str, status: str, run_storage: InMemoryRunStorage,
        run_id: int, run_updates: dict[str, str], expected_stages: frozenset[str],
        rejected_statuses: frozenset[str], error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        row_id = self._rows_by_celery_task_id.get(celery_task_id)
        if row_id is None:
            return False
        row = self._rows[row_id]
        if row.get("status") != "running" or row.get("claim_token") != token or row.get("run_id") != run_id:
            return False
        applied, _ = await run_storage.conditional_update_run(
            run_id, run_updates, expected_stages, rejected_statuses=rejected_statuses,
        )
        await self.finish_if_claimed(celery_task_id, token, status, error_code, error_message)
        return applied

    async def fail_claimed_and_cancel_quota(
        self, celery_task_id: str, token: str, usage_storage: InMemoryUsageStorage,
        error_code: str, error_message: str, run_storage: InMemoryRunStorage | None = None,
        run_id: int | None = None, expected_stages: frozenset[str] = frozenset(),
        billing_outcome: BillingOutcome | None = None,
    ) -> bool:
        async with self._ownership_lock:
            row_id = self._rows_by_celery_task_id.get(celery_task_id)
            if row_id is None:
                return False
            row = self._rows[row_id]
            if row.get("status") != "running" or row.get("claim_token") != token:
                return False
            if run_storage is not None and run_id is not None:
                await run_storage.conditional_update_run(
                    run_id,
                    {"current_stage": "FAILED", "status": "failed"},
                    expected_stages,
                    rejected_statuses=frozenset({"failed", "cancelled", "completed"}),
                )
                if row.get("status") != "running" or row.get("claim_token") != token:
                    return False
            match billing_outcome:
                case None:
                    await usage_storage.finalize_revoked_owned(celery_task_id)
                case BillingOutcome.NOT_STARTED:
                    await usage_storage.cancel_owned(celery_task_id)
                case BillingOutcome.ACCOUNTED:
                    await usage_storage.settle_owned(celery_task_id)
                case BillingOutcome.UNKNOWN:
                    await usage_storage.settle_owned(celery_task_id, billable_unknown=True)
                case unreachable:
                    assert_never(unreachable)
            row.update(
                status="failed", claim_token=None, finished_at=datetime.now(timezone.utc),
                error_code=error_code, error_message=error_message,
            )
            return True

    async def claim_running(self, task_id: int, **kwargs: Any) -> dict[str, Any] | None:
        """Atomically claim a task: only transition from pending/queued/failed to running."""
        row = self._rows.get(task_id)
        if row is None:
            return None
        if row.get("status") not in ("pending", "queued", "failed"):
            return None
        if row.get("claim_token") != kwargs.get("expected_claim_token"):
            return None
        if row.get("error_code") in {
            "reconciler_pending_cleanup",
            "reconciler_stuck_cleanup",
            "reconciler_cleanup_claimed",
            "broker_recovery_cleanup",
            "broker_message_lost",
        }:
            return None
        row["status"] = "running"
        row["claim_token"] = kwargs.get("claim_token")
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

    async def list_reconciliation_pending_tasks(
        self, lease_seconds: int
    ) -> list[dict[str, Any]]:
        lease_cutoff = datetime.now(timezone.utc).timestamp() - lease_seconds
        rows = [
            dict(row)
            for row in self._rows.values()
            if row.get("status") == "failed"
            and (
                row.get("error_code") in {
                    "reconciler_pending_cleanup",
                    "reconciler_stuck_cleanup",
                    "broker_recovery_cleanup",
                }
                or (
                    row.get("error_code") == "reconciler_cleanup_claimed"
                    and row.get("finished_at") is not None
                    and row["finished_at"].timestamp() < lease_cutoff
                )
            )
        ]
        rows.sort(
            key=lambda row: (
                row.get("finished_at") is None,
                row.get("finished_at") or datetime.max.replace(tzinfo=timezone.utc),
            )
        )
        return rows

    async def claim_reconciliation(
        self, task_id: int, claim_token: str, lease_seconds: int
    ) -> dict[str, Any] | None:
        row = self._rows.get(task_id)
        if row is None or row.get("status") != "failed":
            return None
        error_code = row.get("error_code")
        lease_expired = (
            error_code == "reconciler_cleanup_claimed"
            and row.get("finished_at") is not None
            and row["finished_at"].timestamp()
            < datetime.now(timezone.utc).timestamp() - lease_seconds
        )
        if error_code not in {
            "reconciler_pending_cleanup",
            "reconciler_stuck_cleanup",
            "broker_recovery_cleanup",
        } and not lease_expired:
            return None
        if error_code != "reconciler_cleanup_claimed":
            row["error_message"] = error_code
        row["error_code"] = "reconciler_cleanup_claimed"
        row["claim_token"] = claim_token
        row["finished_at"] = datetime.now(timezone.utc)
        return dict(row)

    async def finish_reconciliation(
        self, celery_task_id: str, claim_token: str, error_code: str, error_message: str
    ) -> dict[str, Any] | None:
        row_id = self._rows_by_celery_task_id.get(celery_task_id)
        if row_id is None:
            return None
        row = self._rows[row_id]
        if row.get("error_code") != "reconciler_cleanup_claimed" or row.get("claim_token") != claim_token:
            return None
        row.update(error_code=error_code, error_message=error_message, claim_token=None)
        return dict(row)

    async def release_reconciliation(
        self, celery_task_id: str, claim_token: str
    ) -> dict[str, Any] | None:
        row_id = self._rows_by_celery_task_id.get(celery_task_id)
        if row_id is None:
            return None
        row = self._rows[row_id]
        if row.get("error_code") != "reconciler_cleanup_claimed" or row.get("claim_token") != claim_token:
            return None
        marker = row.get("error_message")
        if marker not in {
            "reconciler_pending_cleanup",
            "reconciler_stuck_cleanup",
            "broker_recovery_cleanup",
        }:
            return None
        row.update(error_code=marker, error_message="Cleanup retry required", claim_token=None)
        return dict(row)

    async def rollback_run_if_task_owner(
        self, celery_task_id: str, run_storage: InMemoryRunStorage,
        run_id: int, eligible_task_types: frozenset[str],
        expected_stages: frozenset[str], rejected_statuses: frozenset[str],
    ) -> tuple[bool, dict[str, Any] | None]:
        async with self._ownership_lock:
            row_id = self._rows_by_celery_task_id.get(celery_task_id)
            owner = self._rows.get(row_id) if row_id is not None else None
            if owner is None or owner.get("run_id") != run_id or owner.get("task_type") not in eligible_task_types:
                return False, await run_storage.get_run(run_id)
            has_newer_owner = any(
                row.get("run_id") == run_id
                and row.get("task_type") == owner.get("task_type")
                and int(row.get("id", 0)) > int(owner.get("id", 0))
                and row.get("status") in {"pending", "queued", "running", "success"}
                for row in self._rows.values()
            )
            if has_newer_owner:
                return False, await run_storage.get_run(run_id)
            return await run_storage.conditional_update_run(
                run_id, {"current_stage": "FAILED", "status": "failed"},
                expected_stages=expected_stages, rejected_statuses=rejected_statuses,
            )

    async def list_broker_recovery_tasks(self) -> list[dict[str, Any]]:
        rows = [
            dict(row)
            for row in self._rows.values()
            if row.get("status") in ("pending", "queued", "running")
        ]
        rows.sort(key=lambda row: row.get("created_at"))
        return rows

    async def get_observed_broker_epoch(self) -> str | None:
        return self._observed_broker_epoch

    async def set_observed_broker_epoch(self, epoch: str) -> None:
        self._observed_broker_epoch = epoch

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
