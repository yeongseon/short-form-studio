# pyright: reportMissingImports=false

from creator_service.usage_service import usage_service
from creator_service.workspace_service import workspace_service
from creator_domain.models.pipeline_run import PipelineRun
from fastapi import APIRouter, Depends, HTTPException, status
from starlette.requests import Request

from shorts_api.auth import (
    CurrentUser,
    require_api_key_header,
    require_run_access,
)

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/workspace/{workspace_id}")
async def get_workspace_usage(
    workspace_id: int,
    request: Request,
    _api_key: str = Depends(require_api_key_header),
) -> dict[str, object]:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not await workspace_service.check_access(workspace_id, user.user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )
    summary = await usage_service.get_monthly_summary(workspace_id)
    return summary.model_dump(mode="json")


@router.get("/run/{run_id}")
async def get_run_usage(
    run_id: int,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
    _api_key: str = Depends(require_api_key_header),
) -> list[dict[str, object]]:
    user, _run = access
    events = await usage_service.list_run_events(run_id, workspace_id=user.workspace_id)
    return [event.model_dump(mode="json") for event in events]
