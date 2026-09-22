"""Routes for the per-project editable Timeline (SF-28).

One authoritative Timeline per Project. GET loads it (404 if absent);
PUT persists it with an atomic revision check (409 on stale write) and
cross-asset validation (400 on unavailable asset). Access is gated by
require_project_access, which returns 404 for cross-tenant access.
"""

import os
from pathlib import Path, PurePosixPath

from creator_domain.models import EncodingProfile, OutputSpec, Timeline
from creator_domain.models.project import Project
from creator_service.media_asset_service import media_asset_service
from creator_service.timeline_compiler import compile_timeline_to_render_plan
from creator_service.timeline_service import timeline_service
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.responses import FileResponse

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


@router.get("/{project_id}/timeline/preview")
async def preview_project_timeline(
    project_id: int,
    output: str = Query(default="short_vertical"),
    encoding: str = Query(default="preview"),
    access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> dict[str, object]:
    """Compile the saved Timeline into the same RenderPlan final rendering consumes.

    The browser preview and the renderer share one compiled source, so what the
    user previews is what gets rendered. Unknown presets -> 400; absent timeline
    -> 404; unavailable media (compiler ValidationError) -> 400 via the handler.
    """
    user, _project = access
    timeline = await timeline_service.load_timeline(
        project_id=project_id, workspace_id=user.workspace_id
    )
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found")

    try:
        output_spec = OutputSpec.preset(output)
        encoding_profile = EncodingProfile.by_name(encoding)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    plan = await compile_timeline_to_render_plan(
        timeline,
        workspace_id=user.workspace_id,
        output_spec=output_spec,
        encoding_profile=encoding_profile,
        asset_resolver=media_asset_service,
    )
    payload = plan.model_dump(mode="json")
    ordered = sorted(timeline.segments, key=lambda segment: segment.timeline_start_seconds)
    for segment, source in zip(payload["segments"], ordered, strict=True):
        segment["media_url"] = f"/api/creator/projects/{project_id}/assets/{source.asset_id}/content"
    payload["timeline_revision"] = timeline.revision
    return payload


@router.get("/{project_id}/assets/{asset_id}/content")
async def get_project_asset_content(
    project_id: int,
    asset_id: int,
    access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> FileResponse:
    user, _project = access
    asset = await media_asset_service.get_asset(asset_id, user.workspace_id)
    if asset is None or asset.project_id != project_id or not asset.storage_key:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.metadata.get("storage_provider", "local") != "local":
        raise HTTPException(status_code=409, detail="Remote media preview is not available")
    key = PurePosixPath(asset.storage_key)
    if key.is_absolute() or ".." in key.parts or "\\" in asset.storage_key:
        raise HTTPException(status_code=404, detail="Asset not found")
    root = Path(os.getenv("ARTIFACT_ROOT", "data/artifacts")).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    allowed = {"image/png", "image/jpeg", "image/webp", "video/mp4", "video/webm"}
    if asset.mime_type not in allowed:
        raise HTTPException(status_code=415, detail="Media cannot be previewed")
    return FileResponse(path, media_type=asset.mime_type, headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    })
