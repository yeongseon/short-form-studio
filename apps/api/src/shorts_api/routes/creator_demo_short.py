from dataclasses import asdict

from creator_domain.models import Project
from creator_service.demo_seed import seed_demo_short
from creator_service.demo_short_flow import build_demo_short_plan
from creator_service.media_asset_service import media_asset_service
from creator_service.project_service import project_service
from creator_service.run_service import run_service
from creator_service.timeline_service import timeline_service
from fastapi import APIRouter, Depends

from shorts_api.auth import CurrentUser, require_project_access, require_workspace_access

router = APIRouter(tags=["demo"])


@router.get("/workspaces/{workspace_id}/demo-short/plan")
async def get_workspace_demo_short_plan(
    workspace_id: int,
    _user: CurrentUser = Depends(require_workspace_access),
) -> dict[str, object]:
    return asdict(build_demo_short_plan())


@router.get("/projects/{project_id}/demo-short/plan")
async def get_demo_short_plan(
    project_id: int,
    _access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> dict[str, object]:
    return asdict(build_demo_short_plan())


@router.post("/workspaces/{workspace_id}/demo-short/runs", status_code=201)
async def create_demo_short_run(
    workspace_id: int,
    _user: CurrentUser = Depends(require_workspace_access),
) -> dict[str, object]:
    result = await seed_demo_short(
        workspace_id=workspace_id,
        project_service=project_service,
        media_asset_service=media_asset_service,
        timeline_service=timeline_service,
        run_service=run_service,
    )
    return {
        "run": result.run.model_dump(mode="json"),
        "seeded_project_id": result.project_id,
        "timeline_id": result.timeline_id,
        "plan": asdict(build_demo_short_plan()),
    }
