# pyright: reportMissingImports=false

from creator_service.usage_service import usage_service
from fastapi import APIRouter, Depends

from shorts_api.auth import get_api_key

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/workspace/{workspace_id}")
async def get_workspace_usage(
    workspace_id: int,
    _api_key: str = Depends(get_api_key),
) -> dict[str, object]:
    summary = await usage_service.get_monthly_summary(workspace_id)
    return summary.model_dump(mode="json")


@router.get("/run/{run_id}")
async def get_run_usage(
    run_id: int,
    _api_key: str = Depends(get_api_key),
) -> list[dict[str, object]]:
    events = await usage_service.list_run_events(run_id)
    return [event.model_dump(mode="json") for event in events]
