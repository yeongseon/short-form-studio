from typing import Any

from fastapi import APIRouter, Depends

from shorts_api.auth import get_current_user

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("")
async def list_workspaces(user: Any = Depends(get_current_user)) -> dict[str, list[dict[str, int | str]]]:
    workspace_id = getattr(user, "workspace_id", None)
    workspace_name = getattr(user, "workspace_name", None)
    return {"workspaces": [{"id": workspace_id or 0, "name": workspace_name or "default"}]}
