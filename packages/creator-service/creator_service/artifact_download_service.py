from __future__ import annotations

import os

from creator_service.artifact_storage_integration import (
    get_artifact_bytes,
    get_artifact_download_path,
)


def resolve_artifact_download(key: str) -> str:
    backend = os.getenv("STORAGE_BACKEND", "local")
    if backend == "local":
        return key
    return get_artifact_download_path(key)


def read_artifact_bytes(key: str) -> bytes:
    return get_artifact_bytes(key)
