"""Routes for creator project management."""
import os
import shutil
from typing import Literal

from creator_domain.models import User
from creator_service.project_service import project_service
from creator_service.run_service import run_service
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from shorts_api.auth import get_current_user
from shorts_api.routes import creator_runs_utils

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    title: str = Field(max_length=200)
    source_type: Literal["idea", "markdown", "pasted_json", "url"]
    idea_brief: str | None = Field(default=None, max_length=5000)
    markdown_source: str | None = Field(default=None, max_length=50000)
    json_script: str | None = Field(default=None, max_length=200000)
    url_source: str | None = Field(default=None, max_length=2000)

@router.post("", status_code=201)
async def create_project(
    request: CreateProjectRequest,
    user: User = Depends(get_current_user),
) -> dict[str, object]:
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
async def update_project(
    project_id: int,
    request: UpdateProjectRequest,
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    project = await project_service.update_project(project_id, title=request.title)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.model_dump(mode="json")

@router.get("/{project_id}")
async def get_project_detail(
    project_id: int,
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    project = await project_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return project.model_dump(mode="json")


@router.get("")
async def list_projects(
    limit: int = Query(default=20, ge=0),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    projects = await project_service.list_projects(limit=limit, offset=offset)
    total = await project_service.count_projects()
    return {
        "projects": [project.model_dump(mode="json") for project in projects],
        "total": total,
    }


async def _cleanup_project_resources(project_id: int) -> list[int]:
    """Revoke active tasks and collect run IDs before project deletion."""
    runs = await run_service.list_runs_by_project(project_id)
    for r in runs:
        if r.active_task_id:
            creator_runs_utils._revoke_active_tasks(r.active_task_id)
    return [r.id for r in runs]


def _remove_run_artifacts(run_ids: list[int]) -> None:
    """Best-effort artifact cleanup for the given run IDs."""
    artifact_root = os.getenv("ARTIFACT_ROOT", "data/artifacts")
    for rid in run_ids:
        run_dir = os.path.join(artifact_root, str(rid))
        if os.path.isdir(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Delete a project and all associated runs (FK cascade)."""
    run_ids = await _cleanup_project_resources(project_id)

    deleted = await project_service.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    _remove_run_artifacts(run_ids)

    return {"deleted": True, "project_id": project_id}
