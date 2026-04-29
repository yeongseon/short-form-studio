from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from creator_service.artifact_storage_integration import get_artifact_download_path
from creator_service.object_storage import get_storage_backend

from .db import fetch_one


class ArtifactDownloadStorageBackend(Protocol):
    async def get_artifact_by_id(self, artifact_id: int) -> dict[str, Any] | None: ...


class InMemoryArtifactDownloadStorage:
    def __init__(self) -> None:
        self._artifacts: list[dict[str, Any]] = []
        self._next_id = 1

    async def save_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        saved = {
            "id": self._next_id,
            "created_at": now,
            **row,
        }
        self._next_id += 1
        self._artifacts.append(saved)
        return dict(saved)

    async def get_artifact_by_id(self, artifact_id: int) -> dict[str, Any] | None:
        for artifact in self._artifacts:
            if artifact["id"] == artifact_id:
                return dict(artifact)
        return None


class PostgresArtifactDownloadStorage:
    async def get_artifact_by_id(self, artifact_id: int) -> dict[str, Any] | None:
        return await fetch_one(
            "SELECT * FROM creator_artifacts WHERE id = $1",
            artifact_id,
        )


class ArtifactDownloadService:
    def __init__(self, storage: ArtifactDownloadStorageBackend | None = None) -> None:
        self.storage = storage if storage is not None else InMemoryArtifactDownloadStorage()

    async def get_artifact_by_id(self, artifact_id: int) -> dict[str, Any] | None:
        return await self.storage.get_artifact_by_id(artifact_id)


def _create_storage() -> ArtifactDownloadStorageBackend:
    import os

    if os.getenv("DATABASE_URL"):
        return PostgresArtifactDownloadStorage()
    return InMemoryArtifactDownloadStorage()


artifact_download_service = ArtifactDownloadService(_create_storage())


def resolve_artifact_download(key: str) -> str:
    return get_artifact_download_path(key)


def read_artifact_bytes(key: str) -> bytes:
    backend = get_storage_backend()
    if not backend.exists(key):
        raise FileNotFoundError(key)
    return backend.download_bytes(key)
