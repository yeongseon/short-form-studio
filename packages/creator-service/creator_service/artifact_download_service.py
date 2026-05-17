from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from creator_service.artifact_storage_integration import get_artifact_download_path
from creator_service.object_storage import get_storage_backend

from .db import execute, fetch_all, fetch_one

logger = logging.getLogger(__name__)


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

    async def delete_artifacts_for_run(self, run_id: int) -> int:
        artifacts = await fetch_all(
            "SELECT id, storage_key, storage_provider FROM creator_artifacts WHERE run_id = $1",
            run_id,
        )
        backend = get_storage_backend()

        deleted_ids: list[int] = []
        failed_count = 0

        for artifact in artifacts:
            key = artifact.get("storage_key")
            artifact_id = artifact.get("id")
            if not isinstance(key, str) or not key:
                if isinstance(artifact_id, int):
                    deleted_ids.append(artifact_id)
                continue
            try:
                backend.delete(key)
                if isinstance(artifact_id, int):
                    deleted_ids.append(artifact_id)
            except Exception:
                failed_count += 1
                logger.exception("Failed deleting artifact key '%s' for run_id=%s", key, run_id)

        if deleted_ids:
            await execute(
                "DELETE FROM creator_artifacts WHERE id = ANY($1::int[])",
                deleted_ids,
            )

        if failed_count:
            logger.warning(
                "%d artifact(s) for run_id=%s could not be deleted from storage; DB rows retained for retry",
                failed_count,
                run_id,
            )

        if failed_count or os.getenv("STORAGE_BACKEND", "local") != "local":
            return failed_count

        artifact_root = Path(os.getenv("ARTIFACT_ROOT", "data/artifacts"))
        run_dir = artifact_root / str(run_id)
        if run_dir.is_dir():
            try:
                for path in sorted(run_dir.rglob("*"), reverse=True):
                    if path.is_file() or path.is_symlink():
                        path.unlink(missing_ok=True)
                    elif path.is_dir():
                        path.rmdir()
                run_dir.rmdir()
            except Exception:
                logger.exception("Failed deleting local run directory '%s'", run_dir)
        return failed_count


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
