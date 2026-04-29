from creator_service.workspace_service import workspace_service
from fastapi import APIRouter, Depends, HTTPException

from shorts_api.auth import get_current_user

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("")
async def list_workspaces(
    user: dict[str, str | int | None] = Depends(get_current_user),
) -> dict[str, list[dict[str, int | str]]]:
    user_id = user.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Invalid user context")

    workspaces = await workspace_service.list_user_workspaces(user_id)
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
