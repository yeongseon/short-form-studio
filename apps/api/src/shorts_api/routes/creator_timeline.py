"""Routes for the per-project editable Timeline (SF-28).

One authoritative Timeline per Project. GET loads it (404 if absent);
PUT persists it with an atomic revision check (409 on stale write) and
cross-asset validation (400 on unavailable asset). Access is gated by
require_project_access, which returns 404 for cross-tenant access.
"""

from creator_domain.models import Timeline
from creator_domain.models.project import Project
from creator_service.timeline_service import timeline_service
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from shorts_api.auth import CurrentUser, require_project_access

router = APIRouter(prefix="/projects", tags=["timeline"])


class SaveTimelineRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    timeline: Timeline


@router.get("/{project_id}/timeline")
async def get_project_timeline(
    project_id: int,
    access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> dict[str, object]:
    user, _project = access
    timeline = await timeline_service.load_timeline(
        project_id=project_id, workspace_id=user.workspace_id
    )
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return timeline.model_dump(mode="json")


@router.put("/{project_id}/timeline")
async def save_project_timeline(
    project_id: int,
    request: SaveTimelineRequest,
    access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> dict[str, object]:
    user, _project = access
    saved = await timeline_service.save_timeline(
        project_id=project_id,
        workspace_id=user.workspace_id,
        timeline=request.timeline,
        expected_revision=request.expected_revision,
    )
    return saved.model_dump(mode="json")
