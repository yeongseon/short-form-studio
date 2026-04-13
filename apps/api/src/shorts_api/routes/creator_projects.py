"""Routes for creator project management."""
from typing import Literal

from creator_service.project_service import project_service
from creator_service.run_service import run_service
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    title: str = Field(max_length=200)
    source_type: Literal["idea", "markdown", "pasted_json", "url"]
    idea_brief: str | None = Field(default=None, max_length=5000)
    markdown_source: str | None = Field(default=None, max_length=50000)
    json_script: str | None = Field(default=None, max_length=200000)
    url_source: str | None = Field(default=None, max_length=2000)

@router.post("", status_code=201)
async def create_project(request: CreateProjectRequest) -> dict[str, object]:
    try:
        project = await project_service.create_project(
            title=request.title,
            source_type=request.source_type,
            idea_brief=request.idea_brief,
            markdown_source=request.markdown_source,
            json_script=request.json_script,
            url_source=request.url_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return project.model_dump(mode="json")




class UpdateProjectRequest(BaseModel):
    title: str = Field(max_length=200)


@router.patch("/{project_id}")
async def update_project(project_id: int, request: UpdateProjectRequest) -> dict[str, object]:
    project = await project_service.update_project(project_id, title=request.title)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.model_dump(mode="json")

@router.get("/{project_id}")
async def get_project_detail(project_id: int) -> dict[str, object]:
    project = await project_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return project.model_dump(mode="json")


@router.get("")
async def list_projects(
    limit: int = Query(default=20, ge=0),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    projects = await project_service.list_projects(limit=limit, offset=offset)
    total = await project_service.count_projects()
    return {
        "projects": [project.model_dump(mode="json") for project in projects],
        "total": total,
    }


@router.delete("/{project_id}")
async def delete_project(project_id: int) -> dict[str, object]:
    """Delete a project and all associated runs (FK cascade)."""
    # First stop any active tasks on runs belonging to this project
    runs = await run_service.list_runs_by_project(project_id)
    for r in runs:
        if r.active_task_id:
            from shorts_api.routes.creator_runs_utils import _revoke_active_tasks
            _revoke_active_tasks(r.active_task_id)

    # Collect run IDs for artifact cleanup before DB cascade deletes them
    run_ids = [r.id for r in runs]

    deleted = await project_service.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    # Best-effort artifact cleanup for all runs
    import os
    import shutil
    artifact_root = os.getenv("ARTIFACT_ROOT", "data/artifacts")
    for rid in run_ids:
        run_dir = os.path.join(artifact_root, str(rid))
        if os.path.isdir(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)

    return {"deleted": True, "project_id": project_id}
