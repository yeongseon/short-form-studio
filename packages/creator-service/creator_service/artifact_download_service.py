from __future__ import annotations

from creator_service.artifact_storage_integration import get_artifact_download_path
from creator_service.object_storage import get_storage_backend


def resolve_artifact_download(key: str) -> str:
    return get_artifact_download_path(key)


def read_artifact_bytes(key: str) -> bytes:
    backend = get_storage_backend()
    if not backend.exists(key):
        raise FileNotFoundError(key)
    return backend.download_bytes(key)
