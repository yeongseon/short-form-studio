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
    "active_task_id",
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

    async def get_run(self, run_id: int) -> dict[str, Any] | None:
        return await fetch_one("SELECT * FROM creator_runs WHERE id = $1", run_id)

    async def update_run(self, run_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        if not updates:
            current = await self.get_run(run_id)
            if current is None:
                raise ValueError(f"Run {run_id} not found")
            return current

        invalid_columns = set(updates) - _UPDATABLE_COLUMNS
        if invalid_columns:
            invalid_list = ", ".join(sorted(invalid_columns))
            raise ValueError(f"Invalid update columns: {invalid_list}")

        keys = list(updates.keys())
        assignments = ", ".join(f"{key} = ${idx}" for idx, key in enumerate(keys, start=2))
        values = [run_id, *[updates[key] for key in keys]]
        query = f"UPDATE creator_runs SET {assignments} WHERE id = $1 RETURNING *"
        updated = await fetch_one(query, *values)
        if updated is None:
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

    async def append_active_task_id(self, run_id: int, task_id: str) -> dict[str, Any]:
        row = await fetch_one(
            "UPDATE creator_runs "
            "SET active_task_id = ("
            "  COALESCE("
            "    CASE WHEN active_task_id IS NOT NULL "
            "         AND left(active_task_id, 1) = '[' "
            "    THEN active_task_id::jsonb "
            "    ELSE '[]'::jsonb "
            "    END, '[]'::jsonb"
            "  ) || to_jsonb($2::text)"
            ")::text "
            "WHERE id = $1 RETURNING *",
            run_id,
            task_id,
        )
        if row is None:
            raise ValueError(f"Run {run_id} not found")
        return row

    async def remove_active_task_id(self, run_id: int, task_id: str) -> dict[str, Any]:
        row = await fetch_one(
            "UPDATE creator_runs "
            "SET active_task_id = COALESCE(("
            "  SELECT jsonb_agg(value) "
            "  FROM jsonb_array_elements_text("
            "    CASE WHEN active_task_id IS NOT NULL "
            "              AND left(active_task_id, 1) = '[' "
            "         THEN active_task_id::jsonb "
            "         WHEN active_task_id IS NULL "
            "         THEN '[]'::jsonb "
            "         ELSE jsonb_build_array(active_task_id) "
            "    END"
            "  ) AS value "
            "  WHERE value <> $2"
            "), '[]'::jsonb)::text "
            "WHERE id = $1 RETURNING *",
            run_id,
            task_id,
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
