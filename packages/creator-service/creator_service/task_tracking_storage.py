from __future__ import annotations

import os
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .run_service import RunStorageBackend
    from .usage_service import UsageStorageBackend


class BillingOutcome(StrEnum):
    NOT_STARTED = "not_started"
    ACCOUNTED = "accounted"
    UNKNOWN = "unknown"


class TaskTrackingStorageBackend(Protocol):
    async def transition_run_and_create_pending(
        self, run_storage: RunStorageBackend, run_id: int, updates: dict[str, Any],
        expected_stages: frozenset[str], task_row: dict[str, Any],
        workspace_id: int | None, rejected_statuses: frozenset[str],
    ) -> tuple[bool, dict[str, Any] | None]: ...
    async def create_task(self, row: dict[str, Any]) -> dict[str, Any] | None: ...
    async def update_task_status(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None: ...
    async def update_task_status_if_running(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None: ...
    async def update_task_status_if_pending(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None: ...
    async def update_task_status_if_active(
        self, celery_task_id: str, status: str, **kwargs: Any
    ) -> dict[str, Any] | None: ...
    async def get_by_celery_id(self, celery_task_id: str) -> dict[str, Any] | None: ...
    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]: ...
    async def claim_running(self, task_id: int, **kwargs: Any) -> dict[str, Any] | None: ...
    async def list_stuck_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]: ...
    async def list_stale_pending_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]: ...
    async def list_reconciliation_pending_tasks(
        self, lease_seconds: int
    ) -> list[dict[str, Any]]: ...
    async def claim_reconciliation(
        self, task_id: int, claim_token: str, lease_seconds: int
    ) -> dict[str, Any] | None: ...
    async def finish_reconciliation(
        self, celery_task_id: str, claim_token: str, error_code: str, error_message: str
    ) -> dict[str, Any] | None: ...
    async def release_reconciliation(
        self, celery_task_id: str, claim_token: str
    ) -> dict[str, Any] | None: ...
    async def rollback_run_if_task_owner(
        self, celery_task_id: str, run_storage: RunStorageBackend,
        run_id: int, eligible_task_types: frozenset[str],
        expected_stages: frozenset[str], rejected_statuses: frozenset[str],
    ) -> tuple[bool, dict[str, Any] | None]: ...
    async def list_broker_recovery_tasks(self) -> list[dict[str, Any]]: ...
    async def get_observed_broker_epoch(self) -> str | None: ...
    async def set_observed_broker_epoch(
        self, epoch: str, expected_previous_epoch: str | None,
        active_generations: frozenset[str] = frozenset(),
    ) -> bool: ...
    async def list_pending_broker_cleanup_generations(self) -> list[str]: ...
    async def complete_broker_cleanup(self, generation: str) -> bool: ...
    async def promote_pending_to_queued(self, celery_task_id: str) -> dict[str, Any] | None: ...
    async def get_active_celery_ids(self, run_id: int) -> list[str]: ...
    async def finish_if_claimed(
        self, celery_task_id: str, token: str, status: str,
        error_code: str | None = None, error_message: str | None = None,
    ) -> dict[str, Any] | None: ...
    async def finish_claimed_run(
        self, celery_task_id: str, token: str, status: str, run_storage: RunStorageBackend,
        run_id: int, run_updates: dict[str, str], expected_stages: frozenset[str],
        rejected_statuses: frozenset[str], error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool: ...
    async def fail_claimed_and_cancel_quota(
        self, celery_task_id: str, token: str, usage_storage: UsageStorageBackend,
        error_code: str, error_message: str, run_storage: RunStorageBackend | None = None,
        run_id: int | None = None, expected_stages: frozenset[str] = frozenset(),
        billing_outcome: BillingOutcome | None = None,
    ) -> bool: ...


def create_task_tracking_storage() -> TaskTrackingStorageBackend:
    if os.getenv("DATABASE_URL"):
        from .postgres_task_tracking_storage import PostgresTaskTrackingStorage

        return PostgresTaskTrackingStorage()
    from .memory_task_tracking_storage import InMemoryTaskTrackingStorage

    return InMemoryTaskTrackingStorage()
