"""Audio service for artifact storage and retrieval.

Manages audio artifacts generated for runs. Each run can have multiple audio
artifacts. Audio artifacts are NOT scene-versioned; the latest artifact
per run is the current one.

Follows the same Protocol → InMemory → Service pattern as
VisualAssetService and ScriptService.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models.audio_artifact import AudioArtifact


# ---------------------------------------------------------------------------
# Storage Protocol
# ---------------------------------------------------------------------------


class AudioStorageBackend(Protocol):
    async def save_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        """Persist an audio artifact row and return stored row with id assigned.

        The storage backend allocates the next id and inserts the row.
        Callers MUST NOT include ``id`` in *row*; the returned dict
        MUST contain the allocated ``id``.
        """
        ...

    async def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        """Fetch a single artifact by id."""
        ...

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]:
        """List all artifacts for a run, newest first."""
        ...

    async def get_latest_by_run(self, run_id: int) -> dict[str, Any] | None:
        """Fetch the most recent artifact for a run."""
        ...


# ---------------------------------------------------------------------------
# In-Memory Storage
# ---------------------------------------------------------------------------


class InMemoryAudioStorage:
    """In-memory storage for audio artifacts."""

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

    async def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        for a in self._artifacts:
            if a["id"] == artifact_id:
                return dict(a)
        return None

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]:
        run_artifacts = [a for a in self._artifacts if a["run_id"] == run_id]
        return [
            dict(a)
            for a in sorted(run_artifacts, key=lambda x: x["created_at"], reverse=True)
        ]

    async def get_latest_by_run(self, run_id: int) -> dict[str, Any] | None:
        artifacts = await self.list_by_run(run_id)
        return artifacts[0] if artifacts else None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AudioService:
    def __init__(self, storage: AudioStorageBackend | None = None) -> None:
        self.storage = storage if storage is not None else InMemoryAudioStorage()

    # -- Create -------------------------------------------------------------

    async def create_artifact(
        self,
        run_id: int,
        path: str,
        *,
        model_used: str | None = None,
        provider_type: str | None = None,
        voice: str | None = None,
    ) -> AudioArtifact:
        """Create a new audio artifact for a run.

        Audio artifacts are NOT versioned. The latest artifact per run
        is the current one.
        """
        metadata = {}
        if model_used is not None:
            metadata["model_used"] = model_used
        if provider_type is not None:
            metadata["provider_type"] = provider_type
        if voice is not None:
            metadata["voice"] = voice

        row = {
            "run_id": run_id,
            "file_path": path,
            "metadata_json": metadata,
        }
        saved = await self.storage.save_artifact(row)

        return self._row_to_artifact(saved)

    # -- Reads --------------------------------------------------------------

    async def get_latest(self, run_id: int) -> AudioArtifact | None:
        """Get the most recent audio artifact for a run."""
        row = await self.storage.get_latest_by_run(run_id)
        if row is None:
            return None
        return self._row_to_artifact(row)

    async def list_by_run(self, run_id: int) -> list[AudioArtifact]:
        """List all audio artifacts for a run, newest first."""
        rows = await self.storage.list_by_run(run_id)
        return [self._row_to_artifact(r) for r in rows]

    async def get_by_id(self, artifact_id: int) -> AudioArtifact | None:
        """Get a single artifact by id."""
        row = await self.storage.get_artifact(artifact_id)
        if row is None:
            return None
        return self._row_to_artifact(row)

    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _row_to_artifact(row: dict[str, Any]) -> AudioArtifact:
        """Convert a storage row to an AudioArtifact domain model."""
        return AudioArtifact.from_row(row)


audio_service = AudioService()
