import mimetypes
import os
from pathlib import Path

from creator_service.media_asset_service import media_asset_service
from creator_service.visual_asset_service import visual_asset_service
from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import FileResponse

from shorts_api.auth import CurrentUser, RunAccessContext, require_run_access, require_workspace_access

router = APIRouter(tags=["assets"])
_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_MEDIA_TYPES = _IMAGE_TYPES | {"video/mp4", "video/webm", "audio/wav", "audio/mpeg", "audio/mp3"}


def _local_path(stored_path: str, *, legacy: bool = False) -> Path:
    root = Path(os.getenv("ARTIFACT_ROOT", "data/artifacts")).resolve()
    source = Path(stored_path)
    if ".." in source.parts or "\\" in stored_path or (source.is_absolute() and not legacy):
        raise HTTPException(status_code=404, detail="Asset not found")
    # Legacy visual rows store ARTIFACT_ROOT-prefixed paths, while storage keys are root-relative.
    if legacy and source.resolve().is_relative_to(root):
        path = source.resolve()
    else:
        path = (root / source).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return path


@router.get("/runs/{run_id}/visual-assets/{asset_id}/content")
async def get_visual_asset_content(
    run_id: int,
    asset_id: int,
    access: RunAccessContext = Depends(require_run_access),
) -> FileResponse:
    _, run = access
    asset = await visual_asset_service.get_asset(asset_id)
    if asset is None or asset.run_id != run.id:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.storage_provider not in {None, "local"}:
        raise HTTPException(status_code=409, detail="Remote media preview is not available")
    path = _local_path(asset.storage_key or asset.asset_path, legacy=not bool(asset.storage_key))
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type not in _IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Media cannot be previewed")
    return FileResponse(path, media_type=mime_type, headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    })


@router.get("/workspaces/{workspace_id}/assets/{asset_id}/content")
async def get_workspace_asset_content(
    workspace_id: int,
    asset_id: int,
    user: CurrentUser = Depends(require_workspace_access),
) -> FileResponse:
    asset = await media_asset_service.get_asset(asset_id, workspace_id)
    if asset is None or not asset.storage_key:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.metadata.get("storage_provider", "local") != "local":
        raise HTTPException(status_code=409, detail="Remote media preview is not available")
    path = _local_path(asset.storage_key)
    if asset.mime_type not in _MEDIA_TYPES:
        raise HTTPException(status_code=415, detail="Media cannot be previewed")
    return FileResponse(path, media_type=asset.mime_type, headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    })
