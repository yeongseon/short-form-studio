from __future__ import annotations

import os
from pathlib import Path

from creator_service.object_storage import StorageResult, get_storage_backend

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


def get_artifact_url(key: str, expires_in: int = 3600) -> str:
    backend = get_storage_backend()
    return backend.download_url(key, expires_in)


def get_artifact_bytes(key: str) -> bytes:
    """Download artifact data by storage key."""
    return get_storage_backend().download_bytes(key)


def get_artifact_download_path(key: str, expires_in: int = 3600) -> str:
    """Get download URL/path for artifact by storage key."""
    return get_storage_backend().download_url(key, expires_in)
