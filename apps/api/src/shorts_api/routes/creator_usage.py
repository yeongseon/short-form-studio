# pyright: reportMissingImports=false

from creator_service.usage_service import usage_service
from fastapi import APIRouter, Depends, Header, HTTPException, status

from shorts_api.auth import get_api_key

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/workspace/{workspace_id}")
async def get_workspace_usage(
    workspace_id: int,
    _api_key: str = Depends(get_api_key),
    authenticated_workspace_id: int | None = Header(default=None, alias="X-Workspace-Id"),
) -> dict[str, object]:
    if authenticated_workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: X-Workspace-Id header is required",
        )
    if authenticated_workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: workspace access denied",
        )
    summary = await usage_service.get_monthly_summary(workspace_id)
    return summary.model_dump(mode="json")


@router.get("/run/{run_id}")
async def get_run_usage(
    run_id: int,
    _api_key: str = Depends(get_api_key),
    authenticated_workspace_id: int | None = Header(default=None, alias="X-Workspace-Id"),
) -> list[dict[str, object]]:
    if authenticated_workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: X-Workspace-Id header is required",
        )
    events = await usage_service.list_run_events(run_id, workspace_id=authenticated_workspace_id)
    return [event.model_dump(mode="json") for event in events]
