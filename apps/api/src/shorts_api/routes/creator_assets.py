"""Workspace-scoped media asset upload routes (SF-03)."""

from __future__ import annotations

from creator_service.media_asset_service import (
    MediaUploadRejected,
    media_asset_service,
)
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from shorts_api.auth import CurrentUser, require_workspace_access

router = APIRouter(prefix="/workspaces", tags=["assets"])

# Defense-in-depth cap on how many bytes we read from an upload stream.
_MAX_IMAGE_BYTES = 25 * 1024 * 1024


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
        raise HTTPException(status_code=400, detail="Upload exceeds maximum allowed size")

    try:
        asset = await media_asset_service.create_image_asset(
            workspace_id=user.workspace_id,
            filename=file.filename or "upload",
            data=data,
            content_type=file.content_type or "application/octet-stream",
            max_bytes=_MAX_IMAGE_BYTES,
        )
    except MediaUploadRejected as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    return asset.model_dump(mode="json")
