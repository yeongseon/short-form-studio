from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import partial

import anyio
from creator_domain.models import MediaAsset, MediaOrigin, MediaType
from pydantic import JsonValue
from creator_service.blocking_io import BlockingIO

from .media_asset_storage import (
    AssetPage as AssetPage,
    InMemoryMediaAssetStorage as InMemoryMediaAssetStorage,
    MediaAssetStorageBackend as MediaAssetStorageBackend,
    MediaStorageBackend as MediaStorageBackend,
)
from .media_probe import (
    ProbeResult as ProbeResult,
    _ProbedMetadata,
    _probe_media_metadata as _probe_media_metadata,
    probe_media_metadata as probe_media_metadata,
    subprocess as subprocess,
    tempfile as tempfile,
)
from .media_upload_validation import (
    MediaUploadRejected as MediaUploadRejected,
    _DEFAULT_MAX_AUDIO_BYTES,
    _DEFAULT_MAX_IMAGE_BYTES,
    _DEFAULT_MAX_VIDEO_BYTES,
    _EXTENSION_BY_MIME,
    _probe_image_dimensions as _probe_image_dimensions,
    _safe_filename,
    _validate_audio_upload as _validate_audio_upload,
    _validate_image_upload as _validate_image_upload,
    _validate_video_upload as _validate_video_upload,
)


class MediaAssetService:
    def __init__(
        self, storage_backend: MediaStorageBackend | None = None,
        asset_storage: MediaAssetStorageBackend | None = None,
    ) -> None:
        self._storage_backend = storage_backend
        self._io = BlockingIO(4)
        if asset_storage is not None:
            self._asset_storage = asset_storage
        elif os.getenv("DATABASE_URL"):
            from .postgres_media_asset_storage import PostgresMediaAssetStorage

            self._asset_storage = PostgresMediaAssetStorage()
        else:
            self._asset_storage = InMemoryMediaAssetStorage()

    def _backend(self) -> MediaStorageBackend:
        if self._storage_backend is not None:
            return self._storage_backend
        from creator_service.object_storage import get_storage_backend

        return get_storage_backend()

    async def create_image_asset(
        self, *, workspace_id: int, filename: str, data: bytes, content_type: str,
        project_id: int | None = None, run_id: int | None = None,
        max_bytes: int = _DEFAULT_MAX_IMAGE_BYTES,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> MediaAsset:
        safe_name = _safe_filename(filename)
        canonical_mime = await self._io.run(
            partial(_validate_image_upload, data, content_type=content_type, max_bytes=max_bytes),
        )
        width, height = await self._io.run(partial(_probe_image_dimensions, data))
        return await self._store_asset(
            workspace_id=workspace_id, safe_name=safe_name, data=data,
            canonical_mime=canonical_mime, media_type=MediaType.IMAGE,
            probed=_ProbedMetadata(width, height, None), project_id=project_id, run_id=run_id,
            metadata=dict(metadata) if metadata is not None else None,
        )

    async def create_generated_image_asset(
        self, *, workspace_id: int, project_id: int, filename: str, data: bytes,
        metadata: dict[str, object] | None = None,
    ) -> MediaAsset:
        """Store verified PNG bytes with generated provenance and protected storage facts."""
        safe_name = _safe_filename(filename)
        mime = await self._io.run(
            partial(_validate_image_upload, data, content_type="image/png"),
        )
        if mime != "image/png":
            raise MediaUploadRejected("Generated image must be PNG")
        width, height = await self._io.run(partial(_probe_image_dimensions, data))
        return await self._store_asset(
            workspace_id=workspace_id, safe_name=safe_name, data=data,
            canonical_mime=mime, media_type=MediaType.IMAGE,
            probed=_ProbedMetadata(width, height, None), project_id=project_id, run_id=None,
            origin=MediaOrigin.GENERATED, metadata=metadata,
        )

    async def create_video_asset(
        self, *, workspace_id: int, filename: str, data: bytes, content_type: str,
        project_id: int | None = None, run_id: int | None = None,
        max_bytes: int = _DEFAULT_MAX_VIDEO_BYTES,
    ) -> MediaAsset:
        safe_name = _safe_filename(filename)
        canonical_mime = _validate_video_upload(data, content_type=content_type, max_bytes=max_bytes)
        probed = await self._io.run(
            partial(_probe_media_metadata, data, kind="video"),
        )
        return await self._store_asset(
            workspace_id=workspace_id, safe_name=safe_name, data=data,
            canonical_mime=canonical_mime, media_type=MediaType.VIDEO,
            probed=probed, project_id=project_id, run_id=run_id,
        )

    async def create_audio_asset(
        self, *, workspace_id: int, filename: str, data: bytes, content_type: str,
        project_id: int | None = None, run_id: int | None = None,
        max_bytes: int = _DEFAULT_MAX_AUDIO_BYTES,
    ) -> MediaAsset:
        safe_name = _safe_filename(filename)
        canonical_mime = _validate_audio_upload(data, content_type=content_type, max_bytes=max_bytes)
        probed = await self._io.run(
            partial(_probe_media_metadata, data, kind="audio"),
        )
        return await self._store_asset(
            workspace_id=workspace_id, safe_name=safe_name, data=data,
            canonical_mime=canonical_mime, media_type=MediaType.AUDIO,
            probed=probed, project_id=project_id, run_id=run_id,
        )

    async def _store_asset(
        self, *, workspace_id: int, safe_name: str, data: bytes,
        canonical_mime: str, media_type: MediaType, probed: _ProbedMetadata,
        project_id: int | None, run_id: int | None,
        origin: MediaOrigin = MediaOrigin.UPLOADED, metadata: dict[str, object] | None = None,
    ) -> MediaAsset:
        extension = _EXTENSION_BY_MIME.get(canonical_mime, "")
        storage_key = f"workspaces/{workspace_id}/assets/{uuid.uuid4().hex}-{safe_name}"
        if extension and not storage_key.endswith(extension):
            storage_key = f"{storage_key}{extension}"
        owned = set(MediaAsset.model_fields) | {
            "asset_path", "size_bytes", "checksum", "storage_provider", "original_filename",
        }
        annotations = {key: value for key, value in (metadata or {}).items() if key not in owned}
        await anyio.lowlevel.checkpoint()
        # Once upload starts, retain ownership through the async metadata save.
        with anyio.CancelScope(shield=True):
            result = await self._io.run(
                lambda: self._backend().upload(storage_key, data, content_type=canonical_mime),
            )
            row: dict[str, object] = {
                "workspace_id": workspace_id, "project_id": project_id, "run_id": run_id,
                "media_type": media_type.value, "origin": origin.value,
                "storage_key": result.key, "mime_type": canonical_mime,
                "width": probed.width, "height": probed.height,
                "duration_seconds": probed.duration_seconds, "source_url": None,
                "metadata": {
                    **annotations, "size_bytes": result.size_bytes, "checksum": result.checksum,
                    "storage_provider": result.storage_provider, "original_filename": safe_name,
                },
                "created_at": datetime.now(timezone.utc),
            }
            saved = await self._asset_storage.save_asset(row)
        return MediaAsset.model_validate(saved)

    async def get_asset(self, asset_id: int, workspace_id: int) -> MediaAsset | None:
        row = await self._asset_storage.get_asset(asset_id, workspace_id)
        return MediaAsset.model_validate(row) if row is not None else None

    async def list_assets(
        self, *, workspace_id: int, media_type: MediaType | None = None,
        project_id: int | None = None, limit: int = 50, offset: int = 0,
    ) -> AssetPage:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        rows, total = await self._asset_storage.list_assets(
            workspace_id, media_type=media_type.value if media_type is not None else None,
            project_id=project_id, limit=limit, offset=offset,
        )
        return AssetPage([MediaAsset.model_validate(row) for row in rows], total, limit, offset)


def _create_service() -> MediaAssetService:
    return MediaAssetService()


media_asset_service = _create_service()
