from __future__ import annotations

from typing import Any

from .db import execute, fetch_all, fetch_one


class PostgresWorkspaceStorage:
    async def create_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = await fetch_one(
            """
            INSERT INTO workspaces (name, slug, owner_id)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            payload.get("name"),
            payload.get("slug"),
            payload.get("owner_id"),
        )
        if row is None:
            raise ValueError("Failed to create workspace")
        return row

    async def get_workspace(self, workspace_id: int) -> dict[str, Any] | None:
        return await fetch_one("SELECT * FROM workspaces WHERE id = $1", workspace_id)

    async def get_workspace_by_slug(self, slug: str) -> dict[str, Any] | None:
        return await fetch_one("SELECT * FROM workspaces WHERE slug = $1", slug)

    async def list_user_workspaces(self, user_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT w.*
            FROM workspaces w
            INNER JOIN workspace_members wm ON wm.workspace_id = w.id
            WHERE wm.user_id = $1
            ORDER BY w.created_at DESC, w.id DESC
            """,
            user_id,
        )

    async def add_member(
        self, workspace_id: int, user_id: int, role: str = "member"
    ) -> dict[str, Any]:
        row = await fetch_one(
            """
            INSERT INTO workspace_members (workspace_id, user_id, role)
            VALUES ($1, $2, $3)
            ON CONFLICT (workspace_id, user_id)
            DO UPDATE SET role = EXCLUDED.role
            RETURNING *
            """,
            workspace_id,
            user_id,
            role,
        )
        if row is None:
            raise ValueError("Failed to add workspace member")
        return row

    async def remove_member(self, workspace_id: int, user_id: int) -> bool:
        row = await fetch_one(
            "DELETE FROM workspace_members WHERE workspace_id = $1 AND user_id = $2 RETURNING user_id",
            workspace_id,
            user_id,
        )
        return row is not None

    async def check_membership(self, workspace_id: int, user_id: int) -> bool:
        row = await fetch_one(
            "SELECT 1 AS member_exists FROM workspace_members WHERE workspace_id = $1 AND user_id = $2",
            workspace_id,
            user_id,
        )
        return row is not None

    async def get_membership(self, workspace_id: int, user_id: int) -> dict[str, Any] | None:
        return await fetch_one(
            "SELECT * FROM workspace_members WHERE workspace_id = $1 AND user_id = $2",
            workspace_id,
            user_id,
        )

    async def set_project_workspace(self, project_id: int, workspace_id: int | None) -> None:
        await execute(
            "UPDATE creator_projects SET workspace_id = $2 WHERE id = $1",
            project_id,
            workspace_id,
        )

    async def set_run_workspace(self, run_id: int, workspace_id: int | None) -> None:
        await execute(
            "UPDATE creator_runs SET workspace_id = $2 WHERE id = $1",
            run_id,
            workspace_id,
        )
