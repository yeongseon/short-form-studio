"""Routes for creator project management."""

import logging
from typing import Any, Awaitable, Callable, Literal, cast

from creator_domain.models.project import Project
from creator_service.artifact_download_service import artifact_download_service
from creator_service.project_service import project_service
from creator_service.run_service import run_service
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from shorts_api.auth import (
    CurrentUser,
    require_current_user,
    require_project_access,
    workspace_service,
)
from shorts_api.routes import creator_runs_utils

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)


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
    user: CurrentUser = Depends(require_current_user),
) -> dict[str, object]:
    user_workspace_id = user.workspace_id
    create_kwargs = {
        "title": request.title,
        "source_type": request.source_type,
        "idea_brief": request.idea_brief,
        "markdown_source": request.markdown_source,
        "json_script": request.json_script,
        "url_source": request.url_source,
    }
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
    access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> dict[str, object]:
    user, project = access
    updated_project = await project_service.update_project(
        project_id,
        title=request.title,
        workspace_id=user.workspace_id,
    )
    if updated_project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated_project.model_dump(mode="json")


@router.get("/{project_id}")
async def get_project_detail(
    project_id: int,
    access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> dict[str, object]:
    user, project = access
    return project.model_dump(mode="json")


@router.get("")
async def list_projects(
    limit: int = Query(default=20, ge=0),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_current_user),
) -> dict[str, object]:
    user_workspace_id = user.workspace_id

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


async def _cleanup_project_resources(project_id: int, workspace_id: int) -> list[int]:
    runs = await run_service.list_runs_by_project(project_id)
    # Mark each run cancelled BEFORE revoking tasks.  This blocks any
    # concurrent dispatch (the same barrier delete_run uses) so no new
    # artifacts can be created while we clean up storage.
    # Fail-closed: if any cancel write fails, abort the entire deletion
    # rather than risk orphaning storage objects.
    for r in runs:
        try:
            await run_service.storage.update_run(
                r.id, {"status": "cancelled"}, workspace_id=workspace_id
            )
        except Exception:
            raise HTTPException(
                status_code=503,
                detail=f"Unable to mark run {r.id} as cancelled before project deletion; retry later",
            ) from None
    for r in runs:
        revoke_ok = await creator_runs_utils._revoke_active_tasks_for_run(r.id)
        if not revoke_ok:
            raise HTTPException(
                status_code=503,
                detail=f"Unable to reliably revoke tasks for run {r.id}; retry later",
            )
    return [r.id for r in runs]


async def _remove_run_artifacts(run_ids: list[int]) -> int:
    total_failures = 0
    for rid in run_ids:
        total_failures += await artifact_download_service.delete_artifacts_for_run(rid)
    return total_failures


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> dict[str, object]:
    user, project = access

    # Mark project as "deleting" BEFORE enumerating runs.  This closes
    # the TOCTOU race where POST /projects/{id}/runs could create a new
    # run after list_runs_by_project() but before the final DB delete,
    # leaving the new run's artifacts permanently orphaned.
    try:
        await project_service.db.update_project(
            project.id, {"status": "deleting"}, workspace_id=user.workspace_id
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to mark project as deleting; retry later",
        ) from None

    run_ids = await _cleanup_project_resources(project.id, workspace_id=user.workspace_id)

    # Delete storage artifacts BEFORE DB rows.  artifact_download_service
    # queries creator_artifacts by run_id — those rows must still exist.
    # If we deleted project/runs first (with FK CASCADE), the artifact
    # query would return nothing and storage objects would be orphaned.
    artifact_failures = await _remove_run_artifacts(run_ids)
    if artifact_failures:
        raise HTTPException(
            status_code=503,
            detail=f"{artifact_failures} artifact(s) could not be deleted from storage; retry later",
        )

    deleted = await project_service.delete_project(project_id, workspace_id=user.workspace_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")

    return {"deleted": True, "project_id": project_id}
