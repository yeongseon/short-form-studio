"""Routes for creator project management."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from creator_service.project_service import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    title: str
    source_type: Literal["idea", "markdown", "url"]
    idea_brief: str | None = None
    markdown_source: str | None = None
    url_source: str | None = None


@router.post("", status_code=201)
async def create_project(request: CreateProjectRequest) -> dict[str, object]:
    try:
        project = await project_service.create_project(
            title=request.title,
            source_type=request.source_type,
            idea_brief=request.idea_brief,
            markdown_source=request.markdown_source,
            url_source=request.url_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
