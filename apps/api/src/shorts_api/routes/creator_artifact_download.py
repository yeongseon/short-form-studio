import os

from creator_domain.sanitize import UnsafePathComponent, sanitize_path_component
from creator_service.artifact_download_service import artifact_download_service
from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}/artifacts/{artifact_id}/download")
async def download_artifact(run_id: int, artifact_id: int) -> FileResponse:
    artifact = await artifact_download_service.get_artifact_by_id(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # TODO: enforce workspace ownership checks after #385 is merged.
    if artifact.get("storage_provider", "local") != "local":
        raise HTTPException(status_code=501, detail="Unsupported storage provider")

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
