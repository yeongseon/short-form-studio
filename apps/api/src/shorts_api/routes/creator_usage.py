# pyright: reportMissingImports=false

from creator_service.usage_service import usage_service
from fastapi import APIRouter, Depends, HTTPException, status
from starlette.requests import Request

from shorts_api.auth import get_api_key, workspace_service

router = APIRouter(prefix="/usage", tags=["usage"])




def _get_authenticated_context(request: Request) -> tuple[int, int]:
    user = getattr(request.state, "user", None)
    if user is None or not user.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.workspace_id:
        raise HTTPException(status_code=403, detail="Workspace context required")
    return int(user.user_id), int(user.workspace_id)


@router.get("/workspace/{workspace_id}")
async def get_workspace_usage(
    workspace_id: int,
    request: Request,
    _api_key: str = Depends(get_api_key),
) -> dict[str, object]:
    authenticated_user_id, authenticated_workspace_id = _get_authenticated_context(request)
    if not await workspace_service.check_access(workspace_id, authenticated_user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )
    summary = await usage_service.get_monthly_summary(workspace_id)
    return summary.model_dump(mode="json")


@router.get("/run/{run_id}")
async def get_run_usage(
    run_id: int,
    request: Request,
    _api_key: str = Depends(get_api_key),
) -> list[dict[str, object]]:
    authenticated_user_id, authenticated_workspace_id = _get_authenticated_context(request)
    if not await workspace_service.check_access(authenticated_workspace_id, authenticated_user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )
    events = await usage_service.list_run_events(run_id, workspace_id=authenticated_workspace_id)
    return [event.model_dump(mode="json") for event in events]
