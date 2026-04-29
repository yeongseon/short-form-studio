from __future__ import annotations

import logging
import os
from pathlib import Path

from creator_service.object_storage import StorageResult, get_storage_backend

logger = logging.getLogger(__name__)
_ARTIFACT_ROOT = Path(os.getenv("ARTIFACT_ROOT", "data/artifacts")).resolve()


def store_artifact_file(
    run_id: int,
    local_path: str | Path,
    content_type: str = "application/octet-stream",
) -> StorageResult | None:
    path = Path(local_path).resolve()
    key = str(path.relative_to(_ARTIFACT_ROOT))
    data = path.read_bytes()
    backend = get_storage_backend()
    try:
        return backend.upload(key, data, content_type=content_type)
    except Exception:
        logger.warning("Object storage upload failed for run %d, local file retained", run_id)
        return None


def get_artifact_url(key: str, expires_in: int = 3600) -> str:
    backend = get_storage_backend()
    return backend.download_url(key, expires_in)


def get_artifact_bytes(key: str) -> bytes:
    """Download artifact data by storage key."""
    return get_storage_backend().download_bytes(key)


def get_artifact_download_path(key: str, expires_in: int = 3600) -> str:
    """Get download URL/path for artifact by storage key."""
    return get_storage_backend().download_url(key, expires_in)
