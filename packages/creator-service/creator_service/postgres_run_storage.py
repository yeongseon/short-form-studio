from __future__ import annotations

from typing import Any

from .db import fetch_all, fetch_one

_UPDATABLE_COLUMNS = {
    "project_id",
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
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            row.get("project_id"),
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

    async def list_runs_by_project(self, project_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            "SELECT * FROM creator_runs WHERE project_id = $1 ORDER BY id DESC",
            project_id,
        )
