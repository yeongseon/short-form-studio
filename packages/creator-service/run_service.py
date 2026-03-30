"""Run service with in-memory storage backend."""

from __future__ import annotations

import json
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "creator-domain"))
domain_models = importlib.import_module("models")
ModelSelection = domain_models.ModelSelection
PipelineRun = domain_models.PipelineRun
RunStage = domain_models.RunStage
REVIEW_STAGES = domain_models.REVIEW_STAGES
can_transition = domain_models.can_transition


class RunStorageBackend(Protocol):
    async def create_run(self, row: dict[str, Any]) -> dict[str, Any]:
        """Persist a run row and return stored row."""
        ...

    async def get_run(self, run_id: int) -> dict[str, Any] | None:
        """Fetch run row by id."""
        ...

    async def update_run(self, run_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update and return run row by id."""
        ...

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, Any],
        expected_stages: frozenset[str],
    ) -> tuple[bool, dict[str, Any] | None]:
        """Atomically update run only if current_stage is in expected_stages.

        Returns (True, updated_row) on success, (False, current_row) if stage
        doesn't match, or (False, None) if run not found.
        """
        ...

class InMemoryRunStorage:
    def __init__(self) -> None:
        self._rows: dict[int, dict[str, Any]] = {}
        self._next_id = 1

    async def create_run(self, row: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        saved = {
            "id": self._next_id,
            "created_at": now,
            "updated_at": now,
            **row,
        }
        self._rows[self._next_id] = saved
        self._next_id += 1
        return dict(saved)

    async def get_run(self, run_id: int) -> dict[str, Any] | None:
        row = self._rows.get(run_id)
        return dict(row) if row is not None else None

    async def update_run(self, run_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        row = self._rows.get(run_id)
        if row is None:
            raise ValueError(f"Run {run_id} not found")

        row.update(updates)
        row["updated_at"] = datetime.now(timezone.utc)
        self._rows[run_id] = row
        return dict(row)

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, Any],
        expected_stages: frozenset[str],
    ) -> tuple[bool, dict[str, Any] | None]:
        row = self._rows.get(run_id)
        if row is None:
            return False, None
        if row.get("current_stage") not in expected_stages:
            return False, dict(row)
        row.update(updates)
        row["updated_at"] = datetime.now(timezone.utc)
        self._rows[run_id] = row
        return True, dict(row)

class RunService:
    def __init__(self, storage: RunStorageBackend):
        self.storage = storage

    async def create_run(
        self,
        project_id: int,
        model_defaults: dict[str, Any] | Any | None,
        style_preset: str,
        metadata: dict[str, Any] | None = None,
    ) -> PipelineRun:
        model_defaults_payload: str | None = None
        if model_defaults is not None:
            model_dump = getattr(model_defaults, "model_dump", None)
            if callable(model_dump):
                model_defaults_payload = json.dumps(model_dump())
            else:
                model_defaults_payload = json.dumps(model_defaults)

        metadata_payload: str | None = None
        if metadata is not None:
            metadata_payload = json.dumps(metadata)

        row = await self.storage.create_run(
            {
                "project_id": project_id,
                "current_stage": RunStage.IDEA_READY.value,
                "status": "pending",
                "review_stage": None,
                "restart_from": None,
                "model_defaults_json": model_defaults_payload,
                "metadata_json": metadata_payload,
                "style_preset": style_preset,
                "started_at": None,
                "finished_at": None,
            }
        )
        return PipelineRun.from_row(row)

    async def get_run(self, run_id: int) -> PipelineRun | None:
        row = await self.storage.get_run(run_id)
        if row is None:
            return None
        return PipelineRun.from_row(row)

    async def restart_run(self, run_id: int, from_stage: str) -> PipelineRun:
        run = await self.get_run(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        try:
            target_stage = RunStage(from_stage)
        except ValueError as exc:
            raise ValueError(f"Invalid stage '{from_stage}'") from exc

        if run.current_stage is None:
            raise ValueError(f"Run {run_id} has no current stage")

        try:
            current_stage = RunStage(run.current_stage)
        except ValueError as exc:
            raise ValueError(f"Invalid current stage '{run.current_stage}' for run {run_id}") from exc

        if not can_transition(current_stage, target_stage):
            raise ValueError(f"Cannot transition from {current_stage.value} to {target_stage.value}")

        row = await self.storage.update_run(
            run_id,
            {
                "restart_from": target_stage.value,
                "current_stage": target_stage.value,
            },
        )
        return PipelineRun.from_row(row)


run_service = RunService(InMemoryRunStorage())
