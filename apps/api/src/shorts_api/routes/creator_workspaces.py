from typing import Any

from creator_service.workspace_service import workspace_service
from fastapi import APIRouter, Depends

from shorts_api.auth import get_current_user

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("")
async def list_workspaces(
    user: Any = Depends(get_current_user),
) -> dict[str, list[dict[str, int | str]]]:
    workspaces = await workspace_service.list_user_workspaces(user.id)
    return {
        "workspaces": [
            {
                "id": workspace.id,
                "name": workspace.name,
                "slug": workspace.slug,
                "owner_id": workspace.owner_id,
            }
            for workspace in workspaces
        ]
    }
