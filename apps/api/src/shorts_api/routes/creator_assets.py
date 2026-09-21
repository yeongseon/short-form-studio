"""Workspace-scoped media asset upload routes (SF-03)."""

from __future__ import annotations

from creator_domain.exceptions import ValidationError
from creator_domain.models import MediaType
from creator_service.media_asset_service import (
    MediaUploadRejected,
    media_asset_service,
)
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from shorts_api.auth import CurrentUser, require_workspace_access

router = APIRouter(prefix="/workspaces", tags=["assets"])

# Defense-in-depth caps on how many bytes we read from an upload stream.
_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_MAX_VIDEO_BYTES = 500 * 1024 * 1024
_MAX_AUDIO_BYTES = 100 * 1024 * 1024


@router.post("/{workspace_id}/assets", status_code=201)
async def upload_image_asset(
    workspace_id: int,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_workspace_access),
) -> dict[str, object]:
    """Upload an image into the caller's workspace as a generic MediaAsset.

    Access is workspace-scoped via ``require_workspace_access`` (404, never 403,
    for unauthorized workspaces — anti-enumeration). Validation, probing, and
    storage are delegated to ``media_asset_service``.
    """
    data = await file.read(_MAX_IMAGE_BYTES + 1)
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValidationError("Upload exceeds maximum allowed size")

    try:
        asset = await media_asset_service.create_image_asset(
            workspace_id=user.workspace_id,
            filename=file.filename or "upload",
            data=data,
            content_type=file.content_type or "application/octet-stream",
            max_bytes=_MAX_IMAGE_BYTES,
        )
    except MediaUploadRejected as error:
        raise ValidationError(str(error)) from error

    return asset.model_dump(mode="json")


@router.post("/{workspace_id}/assets/audio", status_code=201)
async def upload_audio_asset(
    workspace_id: int,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_workspace_access),
) -> dict[str, object]:
    """Upload an audio file into the caller's workspace as a generic MediaAsset.

    Access is workspace-scoped via ``require_workspace_access`` (404, never 403,
    for unauthorized workspaces). The uploaded bytes are stored unchanged, and
    duration is probed by ``media_asset_service``.
    """
    data = await file.read(_MAX_AUDIO_BYTES + 1)
    if len(data) > _MAX_AUDIO_BYTES:
        raise ValidationError("Upload exceeds maximum allowed size")

    try:
        asset = await media_asset_service.create_audio_asset(
            workspace_id=user.workspace_id,
            filename=file.filename or "upload",
            data=data,
            content_type=file.content_type or "application/octet-stream",
            max_bytes=_MAX_AUDIO_BYTES,
        )
    except MediaUploadRejected as error:
        raise ValidationError(str(error)) from error

    return asset.model_dump(mode="json")


@router.post("/{workspace_id}/assets/videos", status_code=201)
async def upload_video_asset(
    workspace_id: int,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_workspace_access),
) -> dict[str, object]:
    """Upload a video into the caller's workspace as a generic MediaAsset.

    Access is workspace-scoped via ``require_workspace_access`` (404, never 403,
    for unauthorized workspaces). The uploaded bytes are stored unchanged, and
    duration/dimensions are probed by ``media_asset_service``.
    """
    data = await file.read(_MAX_VIDEO_BYTES + 1)
    if len(data) > _MAX_VIDEO_BYTES:
        raise ValidationError("Upload exceeds maximum allowed size")

    try:
        asset = await media_asset_service.create_video_asset(
            workspace_id=user.workspace_id,
            filename=file.filename or "upload",
            data=data,
            content_type=file.content_type or "application/octet-stream",
            max_bytes=_MAX_VIDEO_BYTES,
        )
    except MediaUploadRejected as error:
        raise ValidationError(str(error)) from error

    return asset.model_dump(mode="json")


@router.get("/{workspace_id}/assets")
async def list_workspace_assets(
    workspace_id: int,
    media_type: MediaType | None = None,
    project_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_workspace_access),
) -> dict[str, object]:
    """List the caller's workspace assets, uploaded-origin first.

    Workspace-scoped via ``require_workspace_access`` (404 for unauthorized
    workspaces). Only assets in the caller's workspace are ever returned.
    """
    page = await media_asset_service.list_assets(
        workspace_id=user.workspace_id,
        media_type=media_type,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [asset.model_dump(mode="json") for asset in page.items],
        "total": page.total,
        "limit": page.limit,
        "offset": page.offset,
    }


@router.get("/{workspace_id}/assets/{asset_id}")
async def get_workspace_asset(
    workspace_id: int,
    asset_id: int,
    user: CurrentUser = Depends(require_workspace_access),
) -> dict[str, object]:
    """Fetch a single workspace-scoped asset; unknown/unauthorized ids 404."""
    asset = await media_asset_service.get_asset(asset_id, user.workspace_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Not found")
    return asset.model_dump(mode="json")
