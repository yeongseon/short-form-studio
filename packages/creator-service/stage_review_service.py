"""Stage review service with in-memory storage backend."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "creator-domain"))
domain_models = importlib.import_module("models")
RunStage = domain_models.RunStage
REVIEW_STAGES = domain_models.REVIEW_STAGES


class StageReviewStorageBackend(Protocol):
    async def create_review(self, row: dict[str, Any]) -> dict[str, Any]:
        """Persist a review row and return stored row."""
        ...

    async def get_latest_review(
        self, run_id: int, stage_name: str
    ) -> dict[str, Any] | None:
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

    async def get_latest_review(
        self, run_id: int, stage_name: str
    ) -> dict[str, Any] | None:
        matches = [
            r
            for r in self._rows
            if r["run_id"] == run_id and r["stage_name"] == stage_name
        ]
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

    async def get_latest_review(
        self, run_id: int, stage_name: str
    ) -> dict[str, Any] | None:
        """Get the latest review for a run and stage."""
        return await self.storage.get_latest_review(run_id, stage_name)


stage_review_service = StageReviewService(InMemoryStageReviewStorage())
