from __future__ import annotations

from typing import Any

from .db import fetch_all, fetch_one

_UPDATABLE_COLUMNS = {
    "project_id",
    "workspace_id",
    "current_stage",
    "status",
    "review_stage",
    "restart_from",
    "model_defaults_json",
    "metadata_json",
    "style_preset",
    "started_at",
    "finished_at",
}


class PostgresRunStorage:
    async def create_run(self, row: dict[str, Any]) -> dict[str, Any]:
        saved = await fetch_one(
            """
            INSERT INTO creator_runs (
                project_id,
                workspace_id,
                current_stage,
                status,
                review_stage,
                restart_from,
                model_defaults_json,
                metadata_json,
                style_preset,
                started_at,
                finished_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING *
            """,
            row.get("project_id"),
            row.get("workspace_id"),
            row.get("current_stage"),
            row.get("status", "pending"),
            row.get("review_stage"),
            row.get("restart_from"),
            row.get("model_defaults_json"),
            row.get("metadata_json"),
            row.get("style_preset"),
            row.get("started_at"),
            row.get("finished_at"),
        )
        if saved is None:
            raise ValueError("Failed to create run")
        return saved

    async def get_run(self, run_id: int, workspace_id: int | None = None) -> dict[str, Any] | None:
        if workspace_id is None:
            return await fetch_one("SELECT * FROM creator_runs WHERE id = $1", run_id)
        return await fetch_one(
            "SELECT * FROM creator_runs WHERE id = $1 AND workspace_id = $2",
            run_id,
            workspace_id,
        )

    async def update_run(
        self,
        run_id: int,
        updates: dict[str, Any],
        *,
        workspace_id: int | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any] | None:
        if not updates:
            current = await self.get_run(run_id, workspace_id=workspace_id)
            if current is None:
                raise ValueError(f"Run {run_id} not found")
            return current

        invalid_columns = set(updates) - _UPDATABLE_COLUMNS
        if invalid_columns:
            invalid_list = ", ".join(sorted(invalid_columns))
            raise ValueError(f"Invalid update columns: {invalid_list}")

        keys = list(updates.keys())
        assignments = ", ".join(f"{key} = ${idx}" for idx, key in enumerate(keys, start=2))
        values: list[Any] = [run_id, *[updates[key] for key in keys]]
        where_clauses = ["id = $1"]
        next_index = len(values) + 1
        if workspace_id is not None:
            where_clauses.append(f"workspace_id = ${next_index}")
            values.append(workspace_id)
            next_index += 1
        if expected_version is not None:
            where_clauses.append(f"version = ${next_index}")
            values.append(expected_version)
        query = (
            f"UPDATE creator_runs SET {assignments} WHERE {' AND '.join(where_clauses)} RETURNING *"
        )
        updated = await fetch_one(query, *values)
        if updated is None and expected_version is None:
            raise ValueError(f"Run {run_id} not found")
        return updated

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, Any],
        expected_stages: frozenset[str],
    ) -> tuple[bool, dict[str, Any] | None]:
        if not updates:
            current = await self.get_run(run_id)
            if current is None:
                return False, None
            if current.get("current_stage") in expected_stages:
                return True, current
            return False, current

        invalid_columns = set(updates) - _UPDATABLE_COLUMNS
        if invalid_columns:
            invalid_list = ", ".join(sorted(invalid_columns))
            raise ValueError(f"Invalid update columns: {invalid_list}")

        keys = list(updates.keys())
        assignments = ", ".join(f"{key} = ${idx}" for idx, key in enumerate(keys, start=3))
        values = [run_id, list(expected_stages), *[updates[key] for key in keys]]
        query = (
            f"UPDATE creator_runs SET {assignments} "
            "WHERE id = $1 AND current_stage = ANY($2::text[]) RETURNING *"
        )
        updated = await fetch_one(query, *values)
        if updated is not None:
            return True, updated
        current = await self.get_run(run_id)
        if current is None:
            return False, None
        return False, current

    async def merge_model_defaults(self, run_id: int, updates_json: str) -> dict[str, Any]:
        """Atomically merge JSON updates into model_defaults_json using PostgreSQL jsonb."""
        row = await fetch_one(
            "UPDATE creator_runs "
            "SET model_defaults_json = (COALESCE(model_defaults_json, '{}')::jsonb || $2::jsonb)::text "
            "WHERE id = $1 RETURNING *",
            run_id,
            updates_json,
        )
        if row is None:
            raise ValueError(f"Run {run_id} not found")
        return row

    async def list_runs_by_project(self, project_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            "SELECT * FROM creator_runs WHERE project_id = $1 ORDER BY id DESC",
            project_id,
        )

    async def list_runs_by_workspace(self, workspace_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            "SELECT * FROM creator_runs WHERE workspace_id = $1 ORDER BY id DESC",
            workspace_id,
        )

    async def delete_run(self, run_id: int) -> bool:
        """Delete a run by id. Returns True if deleted."""
        result = await fetch_one(
            "DELETE FROM creator_runs WHERE id = $1 RETURNING id",
            run_id,
        )
        return result is not None

    async def delete_runs_by_project(self, project_id: int) -> int:
        """Delete all runs for a project. Returns count of deleted rows."""
        rows = await fetch_all(
            "DELETE FROM creator_runs WHERE project_id = $1 RETURNING id",
            project_id,
        )
        return len(rows)
