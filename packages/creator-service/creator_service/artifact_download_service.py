from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from creator_service.artifact_storage_integration import get_artifact_download_path
from creator_service.object_storage import get_storage_backend

from .db import execute, fetch_all, fetch_one, transaction

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
        # Mark all artifacts as deletion-requested
        if artifacts:
            await execute(
                "UPDATE creator_artifacts SET delete_requested_at = NOW() "
                "WHERE run_id = $1 AND delete_requested_at IS NULL",
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
            except Exception as exc:
                failed_count += 1
                logger.exception("Failed deleting artifact key '%s' for run_id=%s", key, run_id)
                if isinstance(artifact_id, int):
                    await self._record_delete_failure(artifact_id, exc)

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


    @staticmethod
    async def _record_delete_failure(artifact_id: int, exc: Exception) -> None:
        """Persist failure metadata for a single artifact."""
        await execute(
            "UPDATE creator_artifacts "
            "SET delete_failed_at = NOW(), "
            "    delete_error = $2, "
            "    delete_retry_count = COALESCE(delete_retry_count, 0) + 1 "
            "WHERE id = $1",
            artifact_id,
            str(exc)[:500],
        )

    async def sweep_expired(self, batch_size: int = 500) -> int:
        """Mark expired artifacts for deletion.

        Rows whose ``expires_at`` has passed and that haven't already been
        scheduled for deletion get ``delete_requested_at = NOW()``. The actual
        storage + DB row removal is handled by the existing
        ``retry_failed_deletions`` flow (``FOR UPDATE SKIP LOCKED``).

        Returns the number of rows newly marked for deletion.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")

        result = await execute(
            "UPDATE creator_artifacts "
            "SET delete_requested_at = NOW() "
            "WHERE id IN ("
            "    SELECT id FROM creator_artifacts "
            "    WHERE expires_at IS NOT NULL"
            "      AND expires_at < NOW()"
            "      AND delete_requested_at IS NULL"
            "    LIMIT $1"
            ")",
            batch_size,
        )
        # asyncpg CommandComplete returns a status string like 'UPDATE N'.
        status = getattr(result, "statusmessage", "") or ""
        try:
            return int(status.rsplit(" ", 1)[-1])
        except (TypeError, ValueError):
            return 0


    async def retry_failed_deletions(self, max_retries: int = 5) -> int:
        """Reattempt deletion for artifacts that previously failed.

        Runs inside a single database transaction so that
        ``FOR UPDATE SKIP LOCKED`` keeps claimed rows locked until the
        transaction commits, preventing concurrent retry jobs from
        processing the same artifacts.

        Also picks up *stranded* rows — those with ``delete_requested_at``
        set but no ``delete_failed_at`` (e.g. process crashed after storage
        delete succeeded but before the DB row was removed).

        Returns the number of artifacts successfully deleted in this pass.
        """
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")

        async with transaction() as conn:
            # Claim rows with FOR UPDATE SKIP LOCKED inside the transaction.
            # The lock is held until the transaction commits/rolls back,
            # so concurrent callers skip these rows entirely.
            rows = await conn.fetch(
                "SELECT id, storage_key, delete_retry_count "
                "FROM creator_artifacts "
                "WHERE ("
                "  delete_failed_at IS NOT NULL"
                "  OR (delete_requested_at IS NOT NULL AND delete_failed_at IS NULL)"
                ") "
                "AND COALESCE(delete_retry_count, 0) < $1 "
                "AND storage_key IS NOT NULL AND storage_key != \'\' "
                "LIMIT 500 "
                "FOR UPDATE SKIP LOCKED",
                max_retries,
            )
            artifacts = [dict(r) for r in rows]
            if not artifacts:
                return 0

            backend = get_storage_backend()
            deleted_ids: list[int] = []

            for artifact in artifacts:
                key = artifact.get("storage_key")
                artifact_id = artifact.get("id")
                if not isinstance(key, str) or not key or not isinstance(artifact_id, int):
                    continue
                try:
                    backend.delete(key)
                    deleted_ids.append(artifact_id)
                except Exception as exc:
                    logger.exception(
                        "Retry failed for artifact id=%s key=\'%s\'", artifact_id, key
                    )
                    await conn.execute(
                        "UPDATE creator_artifacts "
                        "SET delete_failed_at = NOW(), "
                        "    delete_error = $2, "
                        "    delete_retry_count = COALESCE(delete_retry_count, 0) + 1 "
                        "WHERE id = $1",
                        artifact_id,
                        str(exc)[:500],
                    )

            if deleted_ids:
                await conn.execute(
                    "DELETE FROM creator_artifacts WHERE id = ANY($1::int[])",
                    deleted_ids,
                )

        return len(deleted_ids)


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
