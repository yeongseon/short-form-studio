# pyright: reportMissingImports=false
from creator_service.run_service import run_service
from creator_service.project_service import project_service
from creator_service.task_tracking_service import task_tracking_service
from fastapi import APIRouter, HTTPException, Request

from shorts_api.auth import get_authenticated_workspace_id

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}/tasks")
async def list_run_tasks(run_id: int, request: Request) -> list[dict[str, object]]:
    workspace_id = await get_authenticated_workspace_id(request)
    if workspace_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    project = await project_service.get_project(run.project_id)
    project_workspace_id = getattr(project, "workspace_id", None) if project is not None else None
    if project_workspace_id is not None and workspace_id != project_workspace_id:
        raise HTTPException(status_code=404, detail="Run not found")

    tasks = await task_tracking_service.list_run_tasks(run_id)
    return [task.model_dump(mode="json") for task in tasks]
