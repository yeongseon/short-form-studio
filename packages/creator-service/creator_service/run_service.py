from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models import (
    GENERATING_STAGES,
    STAGE_BACK,
    STAGE_BEFORE_GENERATING,
    PipelineRun,
    RunStage,
    can_transition,
)


class RunStorageBackend(Protocol):
    async def create_run(self, row: dict[str, Any]) -> dict[str, Any]:
        """Persist a run row and return stored row."""
        ...

    async def get_run(self, run_id: int, workspace_id: int | None = None) -> dict[str, Any] | None:
        """Fetch run row by id."""
        ...

    async def update_run(
        self,
        run_id: int,
        updates: dict[str, Any],
        *,
        workspace_id: int | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any] | None:
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

    async def list_runs_by_project(self, project_id: int) -> list[dict[str, Any]]:
        """Return all run rows for a given project, newest first."""
        ...

    async def list_runs_by_workspace(self, workspace_id: int) -> list[dict[str, Any]]:
        """Return all run rows for a workspace, newest first."""
        ...

    async def delete_run(self, run_id: int) -> bool:
        """Delete a run by id. Returns True if deleted."""
        ...

    async def delete_runs_by_project(self, project_id: int) -> int:
        """Delete all runs for a project. Returns count of deleted rows."""
        ...

    async def merge_model_defaults(self, run_id: int, updates_json: str) -> dict[str, Any]:
        """Atomically merge JSON updates into model_defaults_json."""
        ...


class ConflictError(Exception):
    pass


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
            "version": int(row.get("version") or 0),
            **row,
        }
        self._rows[self._next_id] = saved
        self._next_id += 1
        return dict(saved)

    async def get_run(self, run_id: int, workspace_id: int | None = None) -> dict[str, Any] | None:
        row = self._rows.get(run_id)
        if row is None:
            return None
        if workspace_id is not None and row.get("workspace_id") != workspace_id:
            return None
        return dict(row)

    async def update_run(
        self,
        run_id: int,
        updates: dict[str, Any],
        *,
        workspace_id: int | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any] | None:
        row = self._rows.get(run_id)
        if row is None:
            raise ValueError(f"Run {run_id} not found")
        if workspace_id is not None and row.get("workspace_id") != workspace_id:
            raise ValueError(f"Run {run_id} not found")
        current_version = int(row.get("version") or 0)
        if expected_version is not None and current_version != expected_version:
            return None

        row.update(updates)
        row["version"] = current_version + 1
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

    async def list_runs_by_project(self, project_id: int) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self._rows.values() if r.get("project_id") == project_id]
        rows.sort(key=lambda r: r.get("id", 0), reverse=True)
        return rows

    async def list_runs_by_workspace(self, workspace_id: int) -> list[dict[str, Any]]:
        rows = [dict(r) for r in self._rows.values() if r.get("workspace_id") == workspace_id]
        rows.sort(key=lambda r: r.get("id", 0), reverse=True)
        return rows

    async def delete_run(self, run_id: int) -> bool:
        if run_id in self._rows:
            del self._rows[run_id]
            return True
        return False

    async def merge_model_defaults(self, run_id: int, updates_json: str) -> dict[str, Any]:
        row = self._rows.get(run_id)
        if row is None:
            raise ValueError(f"Run {run_id} not found")
        current = json.loads(row.get("model_defaults_json") or "{}")
        updates = json.loads(updates_json)
        merged = {**current, **updates}
        row["model_defaults_json"] = json.dumps(merged)
        row["updated_at"] = datetime.now(timezone.utc)
        self._rows[run_id] = row
        return dict(row)

    async def delete_runs_by_project(self, project_id: int) -> int:
        to_delete = [rid for rid, r in self._rows.items() if r.get("project_id") == project_id]
        for rid in to_delete:
            del self._rows[rid]
        return len(to_delete)


class RunService:
    def __init__(self, storage: RunStorageBackend):
        self.storage = storage

    async def create_run(
        self,
        project_id: int,
        model_defaults: dict[str, Any] | Any | None,
        style_preset: str,
        metadata: dict[str, Any] | None = None,
        current_stage: str = RunStage.IDEA_READY.value,
        status: str = "pending",
        workspace_id: int | None = None,
    ) -> PipelineRun:
        try:
            normalized_stage = RunStage(current_stage).value
        except ValueError as exc:
            raise ValueError(f"Invalid stage '{current_stage}'") from exc

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
                "workspace_id": workspace_id,
                "current_stage": normalized_stage,
                "status": status,
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

    async def get_run(self, run_id: int, workspace_id: int | None = None) -> PipelineRun | None:
        row = await self.storage.get_run(run_id, workspace_id=workspace_id)
        if row is None:
            return None
        return PipelineRun.from_row(row)

    async def restart_run(
        self, run_id: int, from_stage: str, workspace_id: int | None = None
    ) -> PipelineRun:
        run = await self.get_run(run_id, workspace_id=workspace_id)
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
            raise ValueError(
                f"Invalid current stage '{run.current_stage}' for run {run_id}"
            ) from exc

        if not can_transition(current_stage, target_stage):
            raise ValueError(
                f"Cannot transition from {current_stage.value} to {target_stage.value}"
            )

        row = await self.storage.update_run(
            run_id,
            {
                "restart_from": target_stage.value,
                "current_stage": target_stage.value,
            },
            workspace_id=workspace_id,
            expected_version=int(getattr(run, "version", 0) or 0),
        )
        if row is None:
            raise ConflictError(f"Run {run_id} has stale version")
        return PipelineRun.from_row(row)

    async def advance_stage(
        self, run_id: int, target_stage: str, workspace_id: int | None = None
    ) -> PipelineRun:
        """Advance a run to the next stage (approval/forward progression).

        Unlike restart_run, this does NOT set restart_from.
        """
        run = await self.get_run(run_id, workspace_id=workspace_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        try:
            target = RunStage(target_stage)
        except ValueError as exc:
            raise ValueError(f"Invalid stage '{target_stage}'") from exc

        if run.current_stage is None:
            raise ValueError(f"Run {run_id} has no current stage")

        try:
            current = RunStage(run.current_stage)
        except ValueError as exc:
            raise ValueError(
                f"Invalid current stage '{run.current_stage}' for run {run_id}"
            ) from exc

        if not can_transition(current, target):
            raise ValueError(f"Cannot transition from {current.value} to {target.value}")

        row = await self.storage.update_run(
            run_id,
            {"current_stage": target.value},
            workspace_id=workspace_id,
            expected_version=int(getattr(run, "version", 0) or 0),
        )
        if row is None:
            raise ConflictError(f"Run {run_id} has stale version")
        return PipelineRun.from_row(row)

    async def list_runs_by_project(self, project_id: int) -> list[PipelineRun]:
        """Return all runs for a project, newest first."""
        rows = await self.storage.list_runs_by_project(project_id)
        return [PipelineRun.from_row(r) for r in rows]

    async def list_runs_by_workspace(self, workspace_id: int) -> list[PipelineRun]:
        rows = await self.storage.list_runs_by_workspace(workspace_id)
        return [PipelineRun.from_row(r) for r in rows]

    async def stop_run(self, run_id: int, workspace_id: int | None = None) -> PipelineRun:
        """Stop a running pipeline. Only allowed during GENERATING stages.

        Moves current_stage back to the pre-generating actionable stage so
        any surviving worker task's CAS will fail (stage no longer in _SAFE_STAGES).
        """
        run = await self.get_run(run_id, workspace_id=workspace_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        if run.status == "cancelled":
            raise ValueError(f"Run {run_id} is already stopped")

        # Only allow stopping during generating stages
        generating_stage_values = frozenset(s.value for s in GENERATING_STAGES)
        if run.current_stage not in generating_stage_values:
            raise ValueError(
                f"Run {run_id} is in stage '{run.current_stage}', "
                f"can only stop during generating stages"
            )

        # Roll back current_stage to the actionable stage before generation
        current = RunStage(run.current_stage)
        rollback_stage = STAGE_BEFORE_GENERATING[current]

        row = await self.storage.update_run(
            run_id,
            {
                "status": "cancelled",
                "current_stage": rollback_stage.value,
            },
            workspace_id=workspace_id,
            expected_version=int(getattr(run, "version", 0) or 0),
        )
        if row is None:
            raise ConflictError(f"Run {run_id} has stale version")
        return PipelineRun.from_row(row)

    async def resume_run(self, run_id: int, workspace_id: int | None = None) -> PipelineRun:
        """Resume a stopped/cancelled or failed run.

        After stop, current_stage is already at an actionable stage.
        Just resets status to 'running' so the user can re-trigger generation.
        """
        run = await self.get_run(run_id, workspace_id=workspace_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        if run.status not in ("cancelled", "failed"):
            raise ValueError(
                f"Run {run_id} has status '{run.status}', can only resume cancelled or failed runs"
            )

        row = await self.storage.update_run(
            run_id,
            {"status": "running"},
            workspace_id=workspace_id,
            expected_version=int(getattr(run, "version", 0) or 0),
        )
        if row is None:
            raise ConflictError(f"Run {run_id} has stale version")
        return PipelineRun.from_row(row)

    async def go_back(self, run_id: int) -> PipelineRun:
        run = await self.get_run(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        if run.current_stage is None:
            raise ValueError(f"Run {run_id} has no current stage")

        try:
            current = RunStage(run.current_stage)
        except ValueError as exc:
            raise ValueError(f"Invalid current stage '{run.current_stage}'") from exc

        if current not in STAGE_BACK:
            raise ValueError(
                f"Cannot go back from stage '{current.value}'. "
                f"Go-back is only allowed from review stages: "
                f"{', '.join(s.value for s in STAGE_BACK)}"
            )

        target = STAGE_BACK[current]

        ok, row = await self.storage.conditional_update_run(
            run_id,
            {"current_stage": target.value},
            frozenset({current.value}),
        )
        if not ok:
            if row is None:
                raise ValueError(f"Run {run_id} not found")
            raise RuntimeError(
                f"Stage conflict: expected '{current.value}' but run is at '{row.get('current_stage')}'"
            )
        if row is None:
            raise ValueError(f"Run {run_id} not found")
        return PipelineRun.from_row(row)

    async def update_model_defaults(self, run_id: int, updates: dict[str, str]) -> PipelineRun:
        """Atomically merge model default updates (no read-merge-write race)."""
        row = await self.storage.merge_model_defaults(run_id, json.dumps(updates))
        return PipelineRun.from_row(row)

    async def delete_run(self, run_id: int) -> bool:
        """Delete a run and return True if deleted."""
        return await self.storage.delete_run(run_id)


def _create_storage() -> RunStorageBackend:
    import os

    if os.getenv("DATABASE_URL"):
        from .postgres_run_storage import PostgresRunStorage

        return PostgresRunStorage()
    return InMemoryRunStorage()


run_service = RunService(_create_storage())
