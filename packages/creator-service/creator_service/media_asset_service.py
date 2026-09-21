"""Media asset service for the short-first, long-form-ready media core.

Handles workspace-scoped uploaded/generated media assets. This module owns the
image-upload validation, probing, storage write, and MediaAsset persistence.

Follows the Protocol -> InMemory -> Service pattern used across creator-service
(see visual_asset_service). Short form is a product constraint, not a core
domain constraint, so nothing here assumes a short-only duration ceiling.
"""

from __future__ import annotations

import asyncio
import io
import json
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Protocol

from creator_domain.models import MediaAsset, MediaOrigin, MediaType

# 25 MiB default cap for image uploads.
_DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024

_ALLOWED_IMAGE_CONTENT_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    }
)

# Pillow format -> canonical MIME, used to detect spoofed content types.
_PIL_FORMAT_TO_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}

# ffprobe format_name token -> canonical MIME. ffprobe reports comma-separated
# format families (e.g. "mov,mp4,m4a,3gp,3g2,mj2"), so each token is matched.
_FFPROBE_FORMAT_TO_MIME = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "matroska": "video/webm",
    "mov": "video/quicktime",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
}

_EXTENSION_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/ogg": ".ogg",
    "audio/webm": ".weba",
}

# 500 MiB default cap for video uploads.
_DEFAULT_MAX_VIDEO_BYTES = 500 * 1024 * 1024

# 100 MiB default cap for audio uploads.
_DEFAULT_MAX_AUDIO_BYTES = 100 * 1024 * 1024

_ALLOWED_VIDEO_CONTENT_TYPES = frozenset(
    {
        "video/mp4",
        "video/webm",
        "video/quicktime",
    }
)

_ALLOWED_AUDIO_CONTENT_TYPES = frozenset(
    {
        "audio/mpeg",
        "audio/wav",
        "audio/mp4",
        "audio/ogg",
        "audio/webm",
    }
)

_PROBE_TIMEOUT_SECONDS = 30


class MediaUploadRejected(ValueError):
    """Raised when an upload fails validation (bad type, size, or content)."""


class _StorageResult(Protocol):
    key: str
    size_bytes: int
    content_type: str
    checksum: str
    storage_provider: str


class MediaStorageBackend(Protocol):
    def upload(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> _StorageResult: ...


def _probe_image_dimensions(data: bytes) -> tuple[int, int]:
    """Return (width, height) for real image bytes, else raise."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise MediaUploadRejected("File is not a valid image") from error
    return int(width), int(height)


def _detect_image_mime(data: bytes) -> str | None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    if fmt is None:
        return None
    return _PIL_FORMAT_TO_MIME.get(fmt.upper())


def _validate_image_upload(
    data: bytes,
    *,
    content_type: str,
    max_bytes: int = _DEFAULT_MAX_IMAGE_BYTES,
) -> str:
    """Validate declared content type, size, and actual image content.

    Returns the canonical MIME type derived from the real bytes. Never trusts
    the client-declared content type beyond an allowlist gate.
    """
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized not in _ALLOWED_IMAGE_CONTENT_TYPES:
        raise MediaUploadRejected(f"Unsupported image content type: {content_type!r}")
    if not data:
        raise MediaUploadRejected("Empty upload")
    if len(data) > max_bytes:
        raise MediaUploadRejected("Upload exceeds maximum allowed size")

    detected = _detect_image_mime(data)
    if detected is None:
        raise MediaUploadRejected("File content is not a recognized image")
    return detected


@dataclass(frozen=True)
class _ProbedMetadata:
    width: int | None
    height: int | None
    duration_seconds: float | None


@dataclass(frozen=True)
class ProbeResult:
    """Unified probed metadata for any media kind."""

    width: int | None
    height: int | None
    duration_seconds: float | None
    mime_type: str | None
    size_bytes: int


@dataclass(frozen=True)
class AssetPage:
    """A workspace-scoped page of media assets with its total match count."""

    items: list[MediaAsset]
    total: int
    limit: int
    offset: int


def _run_ffprobe(data: bytes) -> dict[str, Any]:
    """Run ffprobe on the bytes via a bounded temp file, returning parsed JSON.

    ffprobe requires a path, so the bytes are written to a temp dir that is
    always cleaned up. The subprocess runs with an argument list (no shell) and a
    hard timeout; any failure means the content is not valid media.
    """
    with tempfile.TemporaryDirectory() as tmp:
        probe_path = Path(tmp) / "probe"
        probe_path.write_bytes(data)
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(probe_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        except (subprocess.TimeoutExpired, OSError) as error:
            raise MediaUploadRejected("Failed to probe media file") from error

    if proc.returncode != 0:
        raise MediaUploadRejected("File content is not a recognized media file")

    try:
        parsed = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as error:
        raise MediaUploadRejected("Failed to parse media metadata") from error
    if not isinstance(parsed, dict):
        raise MediaUploadRejected("Failed to parse media metadata")
    return parsed


def probe_media_metadata(
    data: bytes,
    *,
    kind: str,
    max_bytes: int | None = None,
) -> ProbeResult:
    """Probe width/height/duration/MIME/size for image, video, or audio bytes.

    Images use Pillow; video/audio use a bounded, shell-free ffprobe. Empty,
    oversized, or unrecognized content is rejected. ``kind`` must be one of
    ``image``, ``video``, or ``audio``.
    """
    if kind not in ("image", "video", "audio"):
        raise ValueError(f"Unsupported probe kind: {kind!r}")
    if not data:
        raise MediaUploadRejected("Empty upload")
    if max_bytes is not None and len(data) > max_bytes:
        raise MediaUploadRejected("Upload exceeds maximum allowed size")

    size_bytes = len(data)

    if kind == "image":
        mime = _detect_image_mime(data)
        if mime is None:
            raise MediaUploadRejected("File content is not a recognized image")
        width, height = _probe_image_dimensions(data)
        return ProbeResult(
            width=width,
            height=height,
            duration_seconds=None,
            mime_type=mime,
            size_bytes=size_bytes,
        )

    parsed = _run_ffprobe(data)
    streams = parsed.get("streams") or []
    matching = [s for s in streams if s.get("codec_type") == kind]
    if not matching:
        raise MediaUploadRejected(f"No {kind} stream found in upload")

    stream = matching[0]
    width = stream.get("width")
    height = stream.get("height")

    duration_raw = stream.get("duration")
    if duration_raw is None:
        duration_raw = (parsed.get("format") or {}).get("duration")
    duration: float | None
    try:
        duration = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration = None
    if duration is not None and duration <= 0:
        duration = None

    return ProbeResult(
        width=int(width) if isinstance(width, int) else None,
        height=int(height) if isinstance(height, int) else None,
        duration_seconds=duration,
        mime_type=_ffprobe_mime(parsed, kind),
        size_bytes=size_bytes,
    )


def _ffprobe_mime(parsed: dict[str, Any], kind: str) -> str | None:
    """Map ffprobe's format_name to a canonical MIME for the media kind."""
    fmt = (parsed.get("format") or {}).get("format_name") or ""
    names = {part.strip() for part in fmt.split(",") if part.strip()}
    for format_name, mime in _FFPROBE_FORMAT_TO_MIME.items():
        if format_name in names and mime.startswith(f"{kind}/"):
            return mime
    return None


def _validate_video_upload(
    data: bytes,
    *,
    content_type: str,
    max_bytes: int = _DEFAULT_MAX_VIDEO_BYTES,
) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized not in _ALLOWED_VIDEO_CONTENT_TYPES:
        raise MediaUploadRejected(f"Unsupported video content type: {content_type!r}")
    if not data:
        raise MediaUploadRejected("Empty upload")
    if len(data) > max_bytes:
        raise MediaUploadRejected("Upload exceeds maximum allowed size")
    return normalized


def _validate_audio_upload(
    data: bytes,
    *,
    content_type: str,
    max_bytes: int = _DEFAULT_MAX_AUDIO_BYTES,
) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized not in _ALLOWED_AUDIO_CONTENT_TYPES:
        raise MediaUploadRejected(f"Unsupported audio content type: {content_type!r}")
    if not data:
        raise MediaUploadRejected("Empty upload")
    if len(data) > max_bytes:
        raise MediaUploadRejected("Upload exceeds maximum allowed size")
    return normalized


def _probe_media_metadata(data: bytes, *, kind: str) -> _ProbedMetadata:
    """Probe video/audio dimensions and duration via the unified probe.

    Retained for existing callers that only need the dimensions/duration triple;
    delegates to ``probe_media_metadata`` so the bounded, shell-free ffprobe
    logic lives in one place.
    """
    result = probe_media_metadata(data, kind=kind)
    return _ProbedMetadata(
        width=result.width,
        height=result.height,
        duration_seconds=result.duration_seconds,
    )


class MediaAssetStorageBackend(Protocol):
    """Persistence for MediaAsset rows."""

    async def save_asset(self, row: dict[str, Any]) -> dict[str, Any]:
        """Insert a media asset row and return it with an ``id`` assigned."""
        ...

    async def get_asset(self, asset_id: int, workspace_id: int) -> dict[str, Any] | None:
        """Fetch an asset by id scoped to a workspace (anti-enumeration)."""
        ...

    async def list_assets(
        self,
        workspace_id: int,
        *,
        media_type: str | None = None,
        project_id: int | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return a workspace-scoped ``(rows, total)`` page.

        Rows are ordered uploaded-origin first, then newest-created first, then
        by descending id, so pagination is stable. ``total`` is the full match
        count before limit/offset.
        """
        ...


# Origin ordering for the asset library: uploaded and existing project media are
# surfaced before generated/external so reuse is prioritized over regeneration.
_ORIGIN_SORT_RANK = {
    MediaOrigin.UPLOADED.value: 0,
    MediaOrigin.IMPORTED.value: 1,
    MediaOrigin.EXTERNAL_URL.value: 2,
    MediaOrigin.STOCK.value: 3,
    MediaOrigin.GENERATED.value: 4,
}


def _asset_sort_key(row: dict[str, Any]) -> tuple[int, float, int]:
    """Sort key: uploaded-origin first, then newest-created, then highest id.

    Rank ascends (uploaded before generated); created/id are negated so the
    newest and highest-id rows come first within a rank, giving stable ordering.
    """
    rank = _ORIGIN_SORT_RANK.get(str(row.get("origin")), len(_ORIGIN_SORT_RANK))
    created = row.get("created_at")
    created_ts = created.timestamp() if isinstance(created, datetime) else 0.0
    return (rank, -created_ts, -int(row.get("id", 0)))


class InMemoryMediaAssetStorage:
    """In-memory MediaAsset persistence with atomic id allocation."""

    def __init__(self) -> None:
        self._assets: list[dict[str, Any]] = []
        self._next_id = 1
        self._lock = asyncio.Lock()

    async def save_asset(self, row: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            saved = {"id": self._next_id, **row}
            self._next_id += 1
            self._assets.append(saved)
        return dict(saved)

    async def get_asset(self, asset_id: int, workspace_id: int) -> dict[str, Any] | None:
        for asset in self._assets:
            if asset["id"] == asset_id and asset["workspace_id"] == workspace_id:
                return dict(asset)
        return None

    async def list_assets(
        self,
        workspace_id: int,
        *,
        media_type: str | None = None,
        project_id: int | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        matched = [
            asset
            for asset in self._assets
            if asset["workspace_id"] == workspace_id
            and (media_type is None or asset.get("media_type") == media_type)
            and (project_id is None or asset.get("project_id") == project_id)
        ]
        total = len(matched)
        ordered = sorted(matched, key=_asset_sort_key)
        window = ordered[offset : offset + limit]
        return [dict(row) for row in window], total



def _safe_filename(filename: str) -> str:
    """Validate a client filename is a single safe path component.

    Rejects any name containing path separators or traversal sequences rather
    than silently stripping them, so a crafted name cannot smuggle a different
    basename past validation.
    """
    from creator_domain.sanitize import UnsafePathComponent, sanitize_path_component

    if filename in ("", ".", ".."):
        raise MediaUploadRejected(f"Unsafe filename: {filename!r}")
    if "/" in filename or "\\" in filename or "\x00" in filename:
        raise MediaUploadRejected(f"Unsafe filename: {filename!r}")
    if PurePosixPath(filename).name != filename:
        raise MediaUploadRejected(f"Unsafe filename: {filename!r}")
    try:
        return sanitize_path_component(filename, label="filename")
    except UnsafePathComponent as error:
        raise MediaUploadRejected(f"Unsafe filename: {filename!r}") from error


class MediaAssetService:
    def __init__(
        self,
        storage_backend: MediaStorageBackend | None = None,
        asset_storage: MediaAssetStorageBackend | None = None,
    ) -> None:
        self._storage_backend = storage_backend
        self._asset_storage = asset_storage or InMemoryMediaAssetStorage()

    def _backend(self) -> MediaStorageBackend:
        if self._storage_backend is not None:
            return self._storage_backend
        from creator_service.object_storage import get_storage_backend

        return get_storage_backend()

    async def create_image_asset(
        self,
        *,
        workspace_id: int,
        filename: str,
        data: bytes,
        content_type: str,
        project_id: int | None = None,
        run_id: int | None = None,
        max_bytes: int = _DEFAULT_MAX_IMAGE_BYTES,
    ) -> MediaAsset:
        """Validate, probe, store, and persist an uploaded image asset.

        Rejections (bad type/size/content/filename) raise before any storage
        write, so a rejected upload never leaves a partial artifact.
        """
        safe_name = _safe_filename(filename)
        canonical_mime = _validate_image_upload(
            data, content_type=content_type, max_bytes=max_bytes
        )
        width, height = _probe_image_dimensions(data)
        return await self._store_asset(
            workspace_id=workspace_id,
            safe_name=safe_name,
            data=data,
            canonical_mime=canonical_mime,
            media_type=MediaType.IMAGE,
            probed=_ProbedMetadata(width=width, height=height, duration_seconds=None),
            project_id=project_id,
            run_id=run_id,
        )

    async def create_video_asset(
        self,
        *,
        workspace_id: int,
        filename: str,
        data: bytes,
        content_type: str,
        project_id: int | None = None,
        run_id: int | None = None,
        max_bytes: int = _DEFAULT_MAX_VIDEO_BYTES,
    ) -> MediaAsset:
        """Validate, probe, store, and persist an uploaded video asset.

        The exact uploaded bytes are stored unchanged (source-preserving).
        Rejections raise before any storage write.
        """
        safe_name = _safe_filename(filename)
        canonical_mime = _validate_video_upload(
            data, content_type=content_type, max_bytes=max_bytes
        )
        probed = _probe_media_metadata(data, kind="video")
        return await self._store_asset(
            workspace_id=workspace_id,
            safe_name=safe_name,
            data=data,
            canonical_mime=canonical_mime,
            media_type=MediaType.VIDEO,
            probed=probed,
            project_id=project_id,
            run_id=run_id,
        )

    async def create_audio_asset(
        self,
        *,
        workspace_id: int,
        filename: str,
        data: bytes,
        content_type: str,
        project_id: int | None = None,
        run_id: int | None = None,
        max_bytes: int = _DEFAULT_MAX_AUDIO_BYTES,
    ) -> MediaAsset:
        """Validate, probe, store, and persist an uploaded audio asset.

        The exact uploaded bytes are stored unchanged (source-preserving).
        Rejections raise before any storage write.
        """
        safe_name = _safe_filename(filename)
        canonical_mime = _validate_audio_upload(
            data, content_type=content_type, max_bytes=max_bytes
        )
        probed = _probe_media_metadata(data, kind="audio")
        return await self._store_asset(
            workspace_id=workspace_id,
            safe_name=safe_name,
            data=data,
            canonical_mime=canonical_mime,
            media_type=MediaType.AUDIO,
            probed=probed,
            project_id=project_id,
            run_id=run_id,
        )

    async def _store_asset(
        self,
        *,
        workspace_id: int,
        safe_name: str,
        data: bytes,
        canonical_mime: str,
        media_type: MediaType,
        probed: _ProbedMetadata,
        project_id: int | None,
        run_id: int | None,
    ) -> MediaAsset:
        extension = _EXTENSION_BY_MIME.get(canonical_mime, "")
        storage_key = f"workspaces/{workspace_id}/assets/{uuid.uuid4().hex}-{safe_name}"
        if extension and not storage_key.endswith(extension):
            storage_key = f"{storage_key}{extension}"

        result = self._backend().upload(storage_key, data, content_type=canonical_mime)

        row = {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "run_id": run_id,
            "media_type": media_type.value,
            "origin": MediaOrigin.UPLOADED.value,
            "storage_key": result.key,
            "mime_type": canonical_mime,
            "width": probed.width,
            "height": probed.height,
            "duration_seconds": probed.duration_seconds,
            "source_url": None,
            "metadata": {
                "size_bytes": result.size_bytes,
                "checksum": result.checksum,
                "storage_provider": result.storage_provider,
                "original_filename": safe_name,
            },
            "created_at": datetime.now(timezone.utc),
        }
        saved = await self._asset_storage.save_asset(row)
        return MediaAsset.model_validate(saved)

    async def get_asset(self, asset_id: int, workspace_id: int) -> MediaAsset | None:
        row = await self._asset_storage.get_asset(asset_id, workspace_id)
        if row is None:
            return None
        return MediaAsset.model_validate(row)

    async def list_assets(
        self,
        *,
        workspace_id: int,
        media_type: MediaType | None = None,
        project_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AssetPage:
        """Return a workspace-scoped, filterable, paginated page of assets.

        Ordered uploaded-origin first (reuse over regeneration), then newest.
        Only assets in ``workspace_id`` are ever returned, so a cross-workspace
        lookup yields an empty page rather than leaking existence.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        rows, total = await self._asset_storage.list_assets(
            workspace_id,
            media_type=media_type.value if media_type is not None else None,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
        return AssetPage(
            items=[MediaAsset.model_validate(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )


def _create_service() -> MediaAssetService:
    return MediaAssetService()


media_asset_service = _create_service()
