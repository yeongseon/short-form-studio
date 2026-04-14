"""Subtitle service for artifact storage and retrieval.

Manages subtitle artifacts generated for runs. Each run can have multiple subtitle
artifacts. Subtitle artifacts are NOT scene-versioned; the latest artifact
per run is the current one.

Follows the same Protocol → InMemory → Service pattern as
VisualAssetService and ScriptService.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models.subtitle_artifact import SubtitleArtifact

# ---------------------------------------------------------------------------
# Storage Protocol
# ---------------------------------------------------------------------------


class SubtitleStorageBackend(Protocol):
    async def save_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        """Persist a subtitle artifact row and return stored row with id assigned.

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
    async def get_by_section(self, run_id: int, section_id: str) -> dict[str, Any] | None:
        """Fetch the latest artifact for a run+section."""
        ...

    async def list_by_run_sections(self, run_id: int) -> list[dict[str, Any]]:
        """List all section-level artifacts for a run."""
        ...

    async def delete_by_section(self, run_id: int, section_id: str) -> None:
        """Delete artifacts for a run+section."""
        ...



# ---------------------------------------------------------------------------
# In-Memory Storage
# ---------------------------------------------------------------------------


class InMemorySubtitleStorage:
    """In-memory storage for subtitle artifacts."""

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
        run_artifacts = [
            a
            for a in self._artifacts
            if a["run_id"] == run_id and a.get("scene_id") is None
        ]
        return [
            dict(a)
            for a in sorted(run_artifacts, key=lambda x: x["created_at"], reverse=True)
        ]

    async def get_latest_by_run(self, run_id: int) -> dict[str, Any] | None:
        artifacts = await self.list_by_run(run_id)
        return artifacts[0] if artifacts else None

    async def get_by_section(self, run_id: int, section_id: str) -> dict[str, Any] | None:
        run_artifacts = [
            a for a in self._artifacts
            if a["run_id"] == run_id and a.get("scene_id") == section_id
        ]
        if not run_artifacts:
            return None
        return dict(sorted(run_artifacts, key=lambda x: x["created_at"], reverse=True)[0])

    async def list_by_run_sections(self, run_id: int) -> list[dict[str, Any]]:
        return [
            dict(a) for a in self._artifacts
            if a["run_id"] == run_id and a.get("scene_id") is not None
        ]

    async def delete_by_section(self, run_id: int, section_id: str) -> None:
        self._artifacts = [
            a for a in self._artifacts
            if not (a["run_id"] == run_id and a.get("scene_id") == section_id)
        ]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SubtitleService:
    def __init__(self, storage: SubtitleStorageBackend | None = None) -> None:
        self.storage = storage if storage is not None else InMemorySubtitleStorage()

    # -- Create -------------------------------------------------------------

    async def create_artifact(
        self,
        run_id: int,
        path: str,
        *,
        format: str = "srt",
        model_used: str | None = None,
        provider_type: str | None = None,
    ) -> SubtitleArtifact:
        """Create a new subtitle artifact for a run.

        Subtitle artifacts are NOT versioned. The latest artifact per run
        is the current one.
        """
        metadata = {}
        if format is not None:
            metadata["format"] = format
        if model_used is not None:
            metadata["model_used"] = model_used
        if provider_type is not None:
            metadata["provider_type"] = provider_type

        row = {
            "run_id": run_id,
            "file_path": path,
            "metadata_json": metadata,
        }
        saved = await self.storage.save_artifact(row)

        return self._row_to_artifact(saved)

    # -- Reads --------------------------------------------------------------

    async def get_latest(self, run_id: int) -> SubtitleArtifact | None:
        """Get the most recent subtitle artifact for a run."""
        row = await self.storage.get_latest_by_run(run_id)
        if row is None:
            return None
        return self._row_to_artifact(row)

    async def list_by_run(self, run_id: int) -> list[SubtitleArtifact]:
        """List all subtitle artifacts for a run, newest first."""
        rows = await self.storage.list_by_run(run_id)
        return [self._row_to_artifact(r) for r in rows]

    async def get_by_id(self, artifact_id: int) -> SubtitleArtifact | None:
        """Get a single artifact by id."""
        row = await self.storage.get_artifact(artifact_id)
        if row is None:
            return None
        return self._row_to_artifact(row)

    # -- Per-paragraph methods ------------------------------------------------

    async def create_paragraph_artifact(
        self,
        run_id: int,
        section_id: str,
        path: str,
        *,
        fmt: str = "srt",
        model_used: str | None = None,
        provider_type: str | None = None,
    ) -> SubtitleArtifact:
        """Create a subtitle artifact for a specific paragraph/section."""
        metadata: dict[str, object] = {}
        if fmt is not None:
            metadata["format"] = fmt
        if model_used is not None:
            metadata["model_used"] = model_used
        if provider_type is not None:
            metadata["provider_type"] = provider_type

        row: dict[str, object] = {
            "run_id": run_id,
            "scene_id": section_id,
            "file_path": path,
            "metadata_json": metadata,
        }
        saved = await self.storage.save_artifact(row)
        return self._row_to_artifact(saved)

    async def get_paragraph_subtitles(self, run_id: int, section_id: str) -> SubtitleArtifact | None:
        """Get the latest subtitle artifact for a specific paragraph."""
        row = await self.storage.get_by_section(run_id, section_id)
        if row is None:
            return None
        return self._row_to_artifact(row)

    async def list_paragraph_subtitles(self, run_id: int) -> list[SubtitleArtifact]:
        """List all section-level subtitle artifacts for a run."""
        rows = await self.storage.list_by_run_sections(run_id)
        return [self._row_to_artifact(r) for r in rows]

    async def delete_paragraph_subtitles(self, run_id: int, section_id: str) -> None:
        """Delete subtitle artifacts for a specific paragraph (invalidation)."""
        await self.storage.delete_by_section(run_id, section_id)
    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _row_to_artifact(row: dict[str, Any]) -> SubtitleArtifact:
        """Convert a storage row to a SubtitleArtifact domain model."""
        return SubtitleArtifact.from_row(row)


def _create_storage() -> SubtitleStorageBackend:
    import os

    if os.getenv("DATABASE_URL"):
        from .postgres_subtitle_storage import PostgresSubtitleStorage

        return PostgresSubtitleStorage()
    return InMemorySubtitleStorage()


subtitle_service = SubtitleService(_create_storage())
