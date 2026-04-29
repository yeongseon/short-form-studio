"""Routes for creator project management."""

import os
import shutil
from typing import Any, Literal

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
    user: Any = Depends(get_current_user),
) -> dict[str, object]:
    user_workspace_id = getattr(user, "workspace_id", None)
    create_kwargs = {
        "title": request.title,
        "source_type": request.source_type,
        "idea_brief": request.idea_brief,
        "markdown_source": request.markdown_source,
        "json_script": request.json_script,
        "url_source": request.url_source,
    }
    if user_workspace_id is not None:
        create_kwargs["workspace_id"] = user_workspace_id
    try:
        project = await project_service.create_project(**create_kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return project.model_dump(mode="json")


class UpdateProjectRequest(BaseModel):
    title: str = Field(max_length=200)


@router.patch("/{project_id}")
async def update_project(
    project_id: int,
    request: UpdateProjectRequest,
    user: Any = Depends(get_current_user),
) -> dict[str, object]:
    user_workspace_id = getattr(user, "workspace_id", None)
    current_project = await project_service.get_project(project_id)
    if current_project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project_workspace_id = getattr(current_project, "workspace_id", None)
    if (
        project_workspace_id is not None
        and user_workspace_id is not None
        and project_workspace_id != user_workspace_id
    ):
        raise HTTPException(status_code=404, detail="Project not found")

    project = await project_service.update_project(project_id, title=request.title)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.model_dump(mode="json")


@router.get("/{project_id}")
async def get_project_detail(
    project_id: int,
    user: Any = Depends(get_current_user),
) -> dict[str, object]:
    user_workspace_id = getattr(user, "workspace_id", None)
    project = await project_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project_workspace_id = getattr(project, "workspace_id", None)
    if (
        project_workspace_id is not None
        and user_workspace_id is not None
        and project_workspace_id != user_workspace_id
    ):
        raise HTTPException(status_code=404, detail="Project not found")

    return project.model_dump(mode="json")


@router.get("")
async def list_projects(
    limit: int = Query(default=20, ge=0),
    offset: int = Query(default=0, ge=0),
    user: Any = Depends(get_current_user),
) -> dict[str, object]:
    user_workspace_id = getattr(user, "workspace_id", None)
    if user_workspace_id is None:
        projects = await project_service.list_projects(limit=limit, offset=offset)
        total = await project_service.count_projects()
    else:
        list_projects_fn = getattr(project_service, "list_projects")
        count_projects_fn = getattr(project_service, "count_projects")
        projects = await list_projects_fn(
            limit=limit,
            offset=offset,
            workspace_id=user_workspace_id,
        )
        total = await count_projects_fn(workspace_id=user_workspace_id)
    return {
        "projects": [project.model_dump(mode="json") for project in projects],
        "total": total,
    }


async def _cleanup_project_resources(project_id: int) -> list[int]:
    runs = await run_service.list_runs_by_project(project_id)
    for r in runs:
        if r.active_task_id:
            creator_runs_utils._revoke_active_tasks(r.active_task_id)
    return [r.id for r in runs]


def _remove_run_artifacts(run_ids: list[int]) -> None:
    artifact_root = os.getenv("ARTIFACT_ROOT", "data/artifacts")
    for rid in run_ids:
        run_dir = os.path.join(artifact_root, str(rid))
        if os.path.isdir(run_dir):
            shutil.rmtree(run_dir, ignore_errors=True)


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    user: Any = Depends(get_current_user),
) -> dict[str, object]:
    user_workspace_id = getattr(user, "workspace_id", None)
    get_project = getattr(project_service, "get_project", None)
    if callable(get_project):
        project = await get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        project_workspace_id = getattr(project, "workspace_id", None)
        if (
            project_workspace_id is not None
            and user_workspace_id is not None
            and project_workspace_id != user_workspace_id
        ):
            raise HTTPException(status_code=404, detail="Project not found")

    run_ids = await _cleanup_project_resources(project_id)
    deleted = await project_service.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    _remove_run_artifacts(run_ids)
    return {"deleted": True, "project_id": project_id}
