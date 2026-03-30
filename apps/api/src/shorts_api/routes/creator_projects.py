"""Routes for creator project management."""
# pyright: reportMissingImports=false

import os
import sys
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ValidationError

# Add packages to path for imports
_PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "../../../../..", "packages")
sys.path.insert(0, _PACKAGES_DIR)
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-service"))
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-provider"))

try:
    from creator_service.project_service import project_service
except ImportError:
    from project_service import project_service

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    title: str
    source_type: Literal["idea", "markdown", "url"]
    idea_brief: str | None = None
    markdown_source: str | None = None
    url_source: str | None = None


@router.post("", status_code=201)
async def create_project(payload: dict[str, object]) -> dict[str, object]:
    try:
        request = CreateProjectRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
    return {
        "projects": [project.model_dump(mode="json") for project in projects],
        "total": len(projects),
    }
