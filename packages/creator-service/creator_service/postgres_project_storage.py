from __future__ import annotations

from typing import Any

from .db import fetch_all, fetch_one


class PostgresProjectStorage:
    async def insert_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = await fetch_one(
            """
            INSERT INTO creator_projects (
                title,
                source_type,
                idea_brief,
                markdown_source,
                url_source,
                status
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            """,
            payload.get("title"),
            payload.get("source_type", "idea"),
            payload.get("idea_brief"),
            payload.get("markdown_source"),
            payload.get("url_source"),
            payload.get("status", "draft"),
        )
        if row is None:
            raise ValueError("Failed to insert project")
        return row

    async def fetch_project(self, project_id: int) -> dict[str, Any] | None:
        return await fetch_one("SELECT * FROM creator_projects WHERE id = $1", project_id)

    async def list_projects(self, limit: int, offset: int) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM creator_projects
            ORDER BY created_at DESC, id DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

    async def count_projects(self) -> int:
        row = await fetch_one("SELECT COUNT(*) AS count FROM creator_projects")
        if row is None:
            return 0
        return int(row["count"])

    async def fetch_latest_run_summary(self, project_id: int) -> dict[str, int | str | None] | None:
        row = await fetch_one(
            """
            SELECT id AS run_id, current_stage, status
            FROM creator_runs
            WHERE project_id = $1
            ORDER BY id DESC
            LIMIT 1
            """,
            project_id,
        )
        if row is None:
            return None
        return {
            "run_id": row["run_id"],
            "current_stage": row["current_stage"],
            "status": row["status"],
        }

    async def delete_project(self, project_id: int) -> bool:
        """Delete a project by id. Returns True if deleted.

        Runs are cascade-deleted by FK constraint.
        """
        result = await fetch_one(
            "DELETE FROM creator_projects WHERE id = $1 RETURNING id",
            project_id,
        )
        return result is not None
