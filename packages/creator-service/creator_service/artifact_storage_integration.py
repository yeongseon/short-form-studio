from __future__ import annotations

from creator_service.object_storage import StorageResult, get_storage_backend


def store_artifact_file(relative_key: str, data: bytes, content_type: str) -> StorageResult:
    backend = get_storage_backend()
    return backend.upload(relative_key, data, content_type=content_type)


def get_artifact_download_path(key: str) -> str:
    backend = get_storage_backend()
    return backend.download_url(key)


def get_artifact_bytes(key: str) -> bytes:
    backend = get_storage_backend()
    return backend.download_bytes(key)
