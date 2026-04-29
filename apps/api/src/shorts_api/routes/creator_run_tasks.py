# pyright: reportMissingImports=false
from creator_service.run_service import run_service
from creator_service.task_tracking_service import task_tracking_service
from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}/tasks")
async def list_run_tasks(run_id: int, request: Request) -> list[dict[str, object]]:
    # NOTE: Workspace-scoped filtering will be added after user/workspace model (PR #395) is merged.
    # Currently returns tasks for any run_id without ownership validation.
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Validate workspace ownership using X-Workspace-Id header
    x_workspace_id = request.headers.get("X-Workspace-Id")
    if x_workspace_id is not None:
        # Get the project to check workspace_id
        from creator_service.project_service import project_service
        project = await project_service.get_project(run.project_id)
        if project is not None and project.workspace_id is not None:
            try:
                workspace_id = int(x_workspace_id)
                if workspace_id != project.workspace_id:
                    raise HTTPException(status_code=404, detail="Run not found")
            except (ValueError, TypeError):
                pass  # Invalid header format, allow access for backward compatibility
    
    tasks = await task_tracking_service.list_run_tasks(run_id)
    return [task.model_dump(mode="json") for task in tasks]
