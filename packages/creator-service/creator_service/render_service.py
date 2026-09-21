"""Render service for artifact storage and retrieval.

Manages video render artifacts generated for runs. Each run can have multiple render
artifacts. Render artifacts are NOT scene-versioned; the latest artifact per run
is the current one.

Follows the same Protocol → InMemory → Service pattern as
VisualAssetService and ScriptService.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models.video_artifact import VideoArtifact

from .render_profile import RenderProfile

# ---------------------------------------------------------------------------
# Storage Protocol
# ---------------------------------------------------------------------------


class RenderStorageBackend(Protocol):
    async def save_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        """Persist a render artifact row and return stored row with id assigned.

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


class InMemoryRenderStorage:
    """In-memory storage for render artifacts."""

    def __init__(self) -> None:
        self._artifacts: list[dict[str, Any]] = []
        self._next_id = 1
        self._by_idempotency_key: dict[str, dict[str, Any]] = {}

    async def save_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        idem_key = row.get("idempotency_key")
        if isinstance(idem_key, str) and idem_key in self._by_idempotency_key:
            return dict(self._by_idempotency_key[idem_key])
        now = datetime.now(timezone.utc)
        saved = {
            "id": self._next_id,
            "created_at": now,
            **row,
        }
        self._next_id += 1
        self._artifacts.append(saved)
        if isinstance(idem_key, str):
            self._by_idempotency_key[idem_key] = saved
        return dict(saved)

    async def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        for a in self._artifacts:
            if a["id"] == artifact_id:
                return dict(a)
        return None

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]:
        run_artifacts = [a for a in self._artifacts if a["run_id"] == run_id]
        return [dict(a) for a in sorted(run_artifacts, key=lambda x: x["created_at"], reverse=True)]

    async def get_latest_by_run(self, run_id: int) -> dict[str, Any] | None:
        artifacts = await self.list_by_run(run_id)
        return artifacts[0] if artifacts else None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RenderService:
    def __init__(self, storage: RenderStorageBackend | None = None) -> None:
        self.storage = storage if storage is not None else InMemoryRenderStorage()

    # -- Create -------------------------------------------------------------

    async def create_artifact(
        self,
        run_id: int,
        path: str,
        *,
        render_profile: str | None = None,
        storage_provider: str | None = None,
        storage_key: str | None = None,
        idempotency_key: str | None = None,
    ) -> VideoArtifact:
        """Create a new render artifact for a run.

        Render artifacts are NOT versioned. The latest artifact per run
        is the current one.
        """
        metadata = {}
        if render_profile is not None:
            metadata["render_profile"] = render_profile
        if storage_provider is not None:
            metadata["storage_provider"] = storage_provider
        if storage_key is not None:
            metadata["storage_key"] = storage_key

        row = {
            "run_id": run_id,
            "file_path": path,
            "metadata_json": metadata,
            "idempotency_key": idempotency_key,
        }
        saved = await self.storage.save_artifact(row)

        return self._row_to_artifact(saved)

    # -- Reads --------------------------------------------------------------

    async def get_latest(self, run_id: int) -> VideoArtifact | None:
        """Get the most recent render artifact for a run."""
        row = await self.storage.get_latest_by_run(run_id)
        if row is None:
            return None
        return self._row_to_artifact(row)

    async def list_by_run(self, run_id: int) -> list[VideoArtifact]:
        """List all render artifacts for a run, newest first."""
        rows = await self.storage.list_by_run(run_id)
        return [self._row_to_artifact(r) for r in rows]

    async def get_by_id(self, artifact_id: int) -> VideoArtifact | None:
        """Get a single artifact by id."""
        row = await self.storage.get_artifact(artifact_id)
        if row is None:
            return None
        return self._row_to_artifact(row)

    async def build_render_manifest(
        self,
        run_id: int,
        visual_asset_service: Any,
        audio_service: Any,
        subtitle_service: Any,
        render_profile_name: str = "shorts_default",
    ) -> dict[str, Any]:
        """Build a render manifest for a run.

        Assembles a manifest containing:
        - scenes: list of active scene assets
        - audio_path: latest audio artifact path or None
        - subtitle_path: latest subtitle artifact path or None
        - render_profile: render profile configuration

        Args:
            run_id: Run ID
            visual_asset_service: Service to retrieve visual assets (grouped by scene)
            audio_service: Service to retrieve latest audio
            subtitle_service: Service to retrieve latest subtitles
            render_profile_name: Name of render profile ("shorts_default", "high_quality", "fast_preview")

        Returns:
            dict with keys: run_id, scenes, audio_path, subtitle_path, render_profile
        """
        # Get grouped assets by scene
        grouped_assets = await visual_asset_service.list_by_run(run_id)

        # Build scenes list - pick first active asset from each scene
        scenes = []
        for scene_id in sorted(grouped_assets.keys()):
            assets = grouped_assets[scene_id]
            # Find first active asset
            active_asset = None
            for asset in assets:
                if asset.is_active:
                    active_asset = asset
                    break
            if active_asset:
                scenes.append(
                    {
                        "scene_id": scene_id,
                        "asset_path": active_asset.asset_path,
                        "prompt_snapshot": active_asset.prompt_snapshot,
                    }
                )

        # Get latest audio
        audio_artifact = await audio_service.get_latest(run_id)
        audio_path = audio_artifact.path if audio_artifact else None

        # Get latest subtitle
        subtitle_artifact = await subtitle_service.get_latest(run_id)
        subtitle_path = subtitle_artifact.path if subtitle_artifact else None

        # Resolve render profile
        if render_profile_name == "high_quality":
            profile = RenderProfile.high_quality()
        elif render_profile_name == "fast_preview":
            profile = RenderProfile.fast_preview()
        else:  # default to shorts_default
            profile = RenderProfile.default()

        return {
            "run_id": run_id,
            "scenes": scenes,
            "audio_path": audio_path,
            "subtitle_path": subtitle_path,
            "render_profile": {
                "name": profile.name,
                "width": profile.width,
                "height": profile.height,
                "fps": profile.fps,
                "video_codec": profile.video_codec.value,
                "audio_codec": profile.audio_codec.value,
                "transition_style": profile.transition_style.value,
                "min_duration_seconds": profile.min_duration_seconds,
                "max_duration_seconds": profile.max_duration_seconds,
                "crf": profile.crf,
                "preset": profile.preset,
                "burn_subtitles": profile.burn_subtitles,
                "subtitle_font_size": profile.subtitle_font_size,
            },
        }

    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _row_to_artifact(row: dict[str, Any]) -> VideoArtifact:
        """Convert a storage row to a VideoArtifact domain model."""
        return VideoArtifact.from_row(row)


def _create_storage() -> RenderStorageBackend:
    import os

    if os.getenv("DATABASE_URL"):
        from .postgres_render_storage import PostgresRenderStorage

        return PostgresRenderStorage()
    return InMemoryRenderStorage()


render_service = RenderService(_create_storage())
