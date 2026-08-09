# pyright: reportMissingImports=false

import logging
import os
from datetime import datetime, timezone

from creator_domain.sanitize import UnsafePathComponent, sanitize_path_component
from creator_service.artifact_download_service import artifact_download_service
from creator_service.project_service import project_service
from creator_service.run_service import run_service
from fastapi import APIRouter, Depends, HTTPException
from shorts_api.auth import (
    RunAccessContext,
    require_current_user,
    require_run_access,
    workspace_service,
)
from starlette.responses import FileResponse, RedirectResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}/artifacts/{artifact_id}/download")
async def download_artifact(
    run_id: int,
    artifact_id: int,
    access: RunAccessContext = Depends(require_run_access),
    _user=Depends(require_current_user),
):
    _current_user, run = access
    _ = project_service, run_service, workspace_service, _user

    artifact = await artifact_download_service.get_artifact_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.get("run_id") != run.id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    expires_at = artifact.get("expires_at")
    if (
        expires_at is not None
        and isinstance(expires_at, datetime)
        and expires_at < datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=410, detail="Artifact has expired")

    if artifact.get("storage_provider", "local") != "local":
        from creator_service.object_storage import get_storage_backend

        key = artifact.get("storage_key") or artifact.get("file_path", "")
        try:
            url = get_storage_backend().download_url(str(key))
            return RedirectResponse(url=url, status_code=307)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Storage backend error") from exc


    artifact_root_str = os.getenv("ARTIFACT_ROOT", "data/artifacts")
    artifact_root = os.path.realpath(artifact_root_str)

    # Prefer storage_key (always root-relative) over file_path (absolute since
    # render_video.py stores `{_ARTIFACT_ROOT}/{run_id}/render/...`). Using
    # file_path directly triggers the leading-component guard and returns 404 (#584).
    artifact_path = artifact.get("storage_key") or artifact.get("file_path")
    if not isinstance(artifact_path, str) or not artifact_path:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Legacy rows may still carry an absolute file_path; strip the artifact root
    # so the remaining components are root-relative.
    try:
        rel_path = os.path.relpath(artifact_path, artifact_root_str)
    except ValueError:
        # Different drives on Windows — fall back to the raw value.
        rel_path = artifact_path
    if rel_path == ".." or rel_path.startswith("../") or rel_path.startswith(f"..{os.sep}"):
        # file_path was not under ARTIFACT_ROOT; keep the original so the
        # component guard + commonpath check below reject it safely.
        rel_path = artifact_path

    normalized = rel_path.replace("\\", "/")
    path_components = [c for c in normalized.split("/") if c not in {"", "."}]
    if any(component in {".."} for component in path_components):
        raise HTTPException(status_code=404, detail="Artifact not found")

    try:
        safe_components = [
            sanitize_path_component(component, label=f"artifact_path[{index}]")
            for index, component in enumerate(path_components)
        ]
    except UnsafePathComponent as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    resolved_path = os.path.realpath(os.path.join(artifact_root, *safe_components))
    if os.path.commonpath([artifact_root, resolved_path]) != artifact_root:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not os.path.isfile(resolved_path):
        raise HTTPException(status_code=404, detail="Artifact not found")

    raw_content_type = artifact.get("content_type") or artifact.get("mime_type")
    # Defense in depth: only allow known artifact MIME types and force download.
    # Prevents the API origin from ever rendering HTML/SVG as a document.
    _ALLOWED_CONTENT_TYPES = frozenset({
        "video/mp4",
        "video/webm",
        "audio/wav",
        "audio/mpeg",
        "audio/mp3",
        "image/png",
        "image/jpeg",
        "image/webp",
        "text/vtt",
        "application/x-subrip",
        "application/octet-stream",
    })
    content_type = raw_content_type if raw_content_type in _ALLOWED_CONTENT_TYPES else "application/octet-stream"

    artifact_id_str = str(artifact.get("id", artifact_id))
    filename = safe_components[-1] if safe_components else f"artifact-{artifact_id_str}"
    return FileResponse(
        resolved_path,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
