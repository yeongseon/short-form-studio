from __future__ import annotations

import os
from pathlib import Path

from creator_service.object_storage import StorageResult, get_storage_backend
from creator_service.media_asset_service import media_asset_service
from creator_service.storage_policy import StoragePolicy
from creator_domain.models import MediaType

_ARTIFACT_ROOT = Path(os.getenv("ARTIFACT_ROOT", "data/artifacts")).resolve()


def store_artifact_file(
    _run_id: int,
    local_path: str | Path,
    content_type: str = "application/octet-stream",
) -> StorageResult:
    path = Path(local_path).resolve()
    key = str(path.relative_to(_ARTIFACT_ROOT))
    backend = get_storage_backend()
    with path.open("rb") as file_obj:
        return backend.upload(key, file_obj, content_type=content_type)


def ensure_generation_capacity(incoming_bytes: int = 0) -> None:
    StoragePolicy.from_env().ensure_temp_capacity(incoming_bytes)


async def publish_generated_file(
    *, workspace_id: int, project_id: int, run_id: int,
    local_path: str | Path, content_type: str, media_type: MediaType,
) -> StorageResult:
    path = Path(local_path)
    ensure_generation_capacity(path.stat().st_size)
    asset = await media_asset_service.create_generated_file_asset(
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id,
        filename=path.name,
        path=path,
        content_type=content_type,
        media_type=media_type,
    )
    return StorageResult(
        key=asset.storage_key or "",
        size_bytes=int(asset.metadata["size_bytes"]),
        content_type=content_type,
        checksum=str(asset.metadata["checksum"]),
        storage_provider=str(asset.metadata["storage_provider"]),
    )


async def discard_generated_file(workspace_id: int, storage_key: str) -> None:
    await media_asset_service.discard_generated_asset(workspace_id, storage_key)


def get_artifact_url(key: str, expires_in: int = 3600) -> str:
    backend = get_storage_backend()
    return backend.download_url(key, expires_in)


def get_artifact_bytes(key: str) -> bytes:
    """Download artifact data by storage key."""
    return get_storage_backend().download_bytes(key)


def get_artifact_download_path(key: str, expires_in: int = 3600) -> str:
    """Get download URL/path for artifact by storage key."""
    return get_storage_backend().download_url(key, expires_in)
