# pyright: reportMissingImports=false

import logging
import os
from datetime import datetime, timezone
from creator_domain.sanitize import UnsafePathComponent, sanitize_path_component
from creator_service.artifact_download_service import artifact_download_service
from creator_service.project_service import project_service
from creator_service.run_service import run_service
from fastapi import APIRouter, Depends, HTTPException
from shorts_api.auth import CurrentUser, require_current_user
from starlette.responses import FileResponse, RedirectResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runs"])




@router.get("/runs/{run_id}/artifacts/{artifact_id}/download")
async def download_artifact(
    run_id: int,
    artifact_id: int,
    user: CurrentUser = Depends(require_current_user),
):
    run = await run_service.storage.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    project_id = run.get("project_id")
    if not isinstance(project_id, int):
        raise HTTPException(status_code=404, detail="Run not found")

    project = await project_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    user_workspace_id = user.workspace_id
    project_workspace_id = getattr(project, "workspace_id", None)

    if user_workspace_id is None:
        logger.warning("No authenticated workspace context on artifact access; rejecting request")
        raise HTTPException(status_code=404, detail="Run not found")

    if project_workspace_id is None or user_workspace_id != project_workspace_id:
        raise HTTPException(status_code=404, detail="Run not found")

    artifact = await artifact_download_service.get_artifact_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.get("storage_provider", "local") != "local":
        from creator_service.object_storage import get_storage_backend

        key = artifact.get("storage_key") or artifact.get("file_path", "")
        try:
            url = get_storage_backend().download_url(str(key))
            return RedirectResponse(url=url, status_code=307)
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Storage backend error") from exc

    expires_at = artifact.get("expires_at")
    if (
        expires_at is not None
        and isinstance(expires_at, datetime)
        and expires_at < datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=410, detail="Artifact has expired")

    artifact_root = os.path.realpath(os.getenv("ARTIFACT_ROOT", "data/artifacts"))
    artifact_path = artifact.get("file_path")
    if not isinstance(artifact_path, str) or not artifact_path:
        raise HTTPException(status_code=404, detail="Artifact not found")

    normalized = artifact_path.replace("\\", "/")
    path_components = normalized.split("/")
    if any(component in {"", ".", ".."} for component in path_components):
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

    content_type = artifact.get("content_type") or artifact.get("mime_type")
    return FileResponse(resolved_path, media_type=content_type)
