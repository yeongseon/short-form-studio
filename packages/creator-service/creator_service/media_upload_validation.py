from __future__ import annotations

import io
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

_DEFAULT_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_DEFAULT_MAX_VIDEO_BYTES = 500 * 1024 * 1024
_DEFAULT_MAX_AUDIO_BYTES = 100 * 1024 * 1024

_PIL_FORMAT_TO_MIME = {
    "PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif",
}
_ALLOWED_VIDEO_CONTENT_TYPES = frozenset({"video/mp4", "video/webm", "video/quicktime"})
_ALLOWED_AUDIO_CONTENT_TYPES = frozenset({
    "audio/mpeg", "audio/wav", "audio/mp4", "audio/ogg", "audio/webm",
})
_EXTENSION_BY_MIME = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/mp4": ".m4a",
    "audio/ogg": ".ogg", "audio/webm": ".weba",
}


class MediaUploadRejected(ValueError):
    """Raised before storage when media bytes or filenames fail validation."""


def _probe_image_dimensions(data: bytes | Path) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(data) if isinstance(data, bytes) else data) as image:
            image.verify()
        with Image.open(io.BytesIO(data) if isinstance(data, bytes) else data) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise MediaUploadRejected("File is not a valid image") from error
    return int(width), int(height)


def _detect_image_mime(data: bytes | Path) -> str | None:
    try:
        with Image.open(io.BytesIO(data) if isinstance(data, bytes) else data) as image:
            fmt = image.format
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    return _PIL_FORMAT_TO_MIME.get(fmt.upper()) if fmt is not None else None


def _validate_image_upload(
    data: bytes, *, content_type: str, max_bytes: int = _DEFAULT_MAX_IMAGE_BYTES,
) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized not in _PIL_FORMAT_TO_MIME.values():
        raise MediaUploadRejected(f"Unsupported image content type: {content_type!r}")
    if not data:
        raise MediaUploadRejected("Empty upload")
    if len(data) > max_bytes:
        raise MediaUploadRejected("Upload exceeds maximum allowed size")
    detected = _detect_image_mime(data)
    if detected is None:
        raise MediaUploadRejected("File content is not a recognized image")
    return detected


def _validate_video_upload(
    data: bytes, *, content_type: str, max_bytes: int = _DEFAULT_MAX_VIDEO_BYTES,
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
    data: bytes, *, content_type: str, max_bytes: int = _DEFAULT_MAX_AUDIO_BYTES,
) -> str:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized not in _ALLOWED_AUDIO_CONTENT_TYPES:
        raise MediaUploadRejected(f"Unsupported audio content type: {content_type!r}")
    if not data:
        raise MediaUploadRejected("Empty upload")
    if len(data) > max_bytes:
        raise MediaUploadRejected("Upload exceeds maximum allowed size")
    return normalized


def _safe_filename(filename: str) -> str:
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
