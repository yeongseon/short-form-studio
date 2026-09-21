# pyright: reportMissingImports=false

from creator_service.db import get_pool
from fastapi import APIRouter, Depends

from shorts_api.auth import CurrentUser, require_current_user

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("")
async def list_workspaces(
    user: CurrentUser = Depends(require_current_user),
) -> dict[str, list[dict[str, int | str]]]:
    user_id = user.user_id
    pool = await get_pool()
    async with pool.acquire() as connection:
        member_rows = await connection.fetch(
            "SELECT workspace_id FROM workspace_members WHERE user_id = $1 ORDER BY workspace_id",
            user_id,
        )

        workspace_ids = [
            int(row["workspace_id"]) for row in member_rows if row.get("workspace_id") is not None
        ]
        if not workspace_ids:
            return {"workspaces": []}

        workspace_rows = await connection.fetch(
            "SELECT id, name FROM workspaces WHERE id = ANY($1::int[]) ORDER BY id",
            workspace_ids,
        )

    workspaces = [
        {
            "id": int(row["id"]),
            "name": str(row.get("name") or f"workspace-{int(row['id'])}"),
        }
        for row in workspace_rows
        if row.get("id") is not None
    ]
    return {"workspaces": workspaces}
