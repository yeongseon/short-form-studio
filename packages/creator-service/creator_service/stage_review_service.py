"""Stage review service with in-memory storage backend."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models import REVIEW_STAGES, RunStage, can_transition

logger = logging.getLogger(__name__)


class StageReviewStorageBackend(Protocol):
    async def create_review(self, row: dict[str, Any]) -> dict[str, Any]:
        """Persist a review row and return stored row."""
        ...

    async def get_latest_review(self, run_id: int, stage_name: str) -> dict[str, Any] | None:
        """Fetch the most recent review for a run and stage."""
        ...


class InMemoryStageReviewStorage:
    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._next_id = 1

    async def create_review(self, row: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        saved = {
            "id": self._next_id,
            "created_at": now,
            **row,
        }
        self._rows.append(saved)
        self._next_id += 1
        return dict(saved)

    async def get_latest_review(self, run_id: int, stage_name: str) -> dict[str, Any] | None:
        matches = [r for r in self._rows if r["run_id"] == run_id and r["stage_name"] == stage_name]
        if not matches:
            return None
        return dict(max(matches, key=lambda r: r["created_at"]))


class StageReviewService:
    def __init__(self, storage: StageReviewStorageBackend) -> None:
        self.storage = storage

    async def record_approval(
        self,
        run_id: int,
        stage_name: str,
        reviewer: str = "agent",
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record an approval for a review stage.

        Validates that stage_name is a valid review stage.
        Returns the persisted review row.
        """
        try:
            stage = RunStage(stage_name)
        except ValueError as exc:
            raise ValueError(f"Invalid stage '{stage_name}'") from exc

        if stage not in REVIEW_STAGES:
            raise ValueError(
                f"Stage '{stage_name}' is not a review stage. "
                f"Valid review stages: {sorted(s.value for s in REVIEW_STAGES)}"
            )

        row = await self.storage.create_review(
            {
                "run_id": run_id,
                "stage_name": stage_name,
                "review_status": "approved",
                "reviewer": reviewer,
                "notes": notes,
            }
        )
        return row

    async def approve_and_advance(
        self,
        *,
        run_service: Any,
        run_id: int,
        stage_name: str,
        target_stage: str,
        reviewer: str = "agent",
        notes: str | None = None,
        workspace_id: int | None = None,
        extra_updates: dict[str, Any] | None = None,
    ) -> Any:
        """Atomically validate stage, record approval, and advance.

        Uses conditional_update_run for atomic stage transition so that a
        concurrent change between the approval record and the advance cannot
        leave the system in an inconsistent state.

        Returns the updated PipelineRun.

        Raises:
            ValueError: If run not found, stage mismatch, or invalid transition.
        """
        # 1. Validate stage_name is a review stage
        try:
            stage = RunStage(stage_name)
        except ValueError as exc:
            raise ValueError(f"Invalid stage '{stage_name}'") from exc

        if stage not in REVIEW_STAGES:
            raise ValueError(
                f"Stage '{stage_name}' is not a review stage. "
                f"Valid review stages: {sorted(s.value for s in REVIEW_STAGES)}"
            )

        # 2. Validate target_stage is a valid enum and transition is allowed
        try:
            target = RunStage(target_stage)
        except ValueError as exc:
            raise ValueError(f"Invalid target stage '{target_stage}'") from exc

        if not can_transition(stage, target):
            raise ValueError(f"Cannot transition from {stage.value} to {target.value}")

        # 3. Atomically advance stage (CAS — fails if stage changed concurrently)
        updates: dict[str, Any] = {"current_stage": target.value}
        # Capture original values of extra fields for rollback
        original_extra_values: dict[str, Any] = {}
        if extra_updates:
            updates.update(extra_updates)
            # Read current run to capture pre-update values
            current_run = await run_service.get_run(run_id, workspace_id=workspace_id)
            if current_run is not None:
                for key in extra_updates:
                    original_extra_values[key] = getattr(current_run, key, None)
        ok, row = await run_service.storage.conditional_update_run(
            run_id,
            updates,
            frozenset({stage.value}),
            workspace_id=workspace_id,
        )

        if not ok:
            if row is None:
                raise ValueError(f"Run {run_id} not found")
            raise ValueError(
                f"Stage conflict: run is now in '{row.get('current_stage')}', "
                f"expected '{stage_name}'"
            )

        # 4. Record approval (only after CAS succeeds — no orphan reviews)
        try:
            await self.storage.create_review(
                {
                    "run_id": run_id,
                    "stage_name": stage_name,
                    "review_status": "approved",
                    "reviewer": reviewer,
                    "notes": notes,
                }
            )
        except Exception as exc:
            # Roll back ALL fields changed by the CAS (stage + extra_updates).
            rollback_updates: dict[str, Any] = {"current_stage": stage.value}
            if original_extra_values:
                # Restore extra fields to their exact pre-update values
                for key, original_value in original_extra_values.items():
                    rollback_updates[key] = original_value
            rollback_ok, _ = await run_service.storage.conditional_update_run(
                run_id,
                rollback_updates,
                frozenset({target.value}),
                workspace_id=workspace_id,
            )
            if not rollback_ok:
                logger.critical(
                    "INCONSISTENCY: review insert failed AND rollback failed "
                    "for run %s (stage %s -> %s). Manual intervention required.",
                    run_id,
                    stage.value,
                    target.value,
                )
                raise RuntimeError(
                    f"Stage rollback failed for run {run_id}: review insert failed "
                    f"and stage could not be restored from {target.value} to {stage.value}. "
                    f"Original error: {exc}"
                ) from exc
            raise

        updated_run = await run_service.get_run(run_id, workspace_id=workspace_id)
        if updated_run is None:
            raise ValueError(f"Run {run_id} not found")
        return updated_run

    async def get_latest_review(self, run_id: int, stage_name: str) -> dict[str, Any] | None:
        """Get the latest review for a run and stage."""
        return await self.storage.get_latest_review(run_id, stage_name)


def _create_storage() -> StageReviewStorageBackend:
    import os

    if os.getenv("DATABASE_URL"):
        from .postgres_stage_review_storage import PostgresStageReviewStorage

        return PostgresStageReviewStorage()
    return InMemoryStageReviewStorage()


stage_review_service = StageReviewService(_create_storage())
