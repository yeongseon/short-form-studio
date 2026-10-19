from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO, Final, Literal

import anyio

from .blocking_io import BlockingIO
from .media_probe import ProbeResult, probe_media_metadata
from .media_upload_validation import (
    MediaUploadRejected,
    _ALLOWED_AUDIO_CONTENT_TYPES,
    _ALLOWED_VIDEO_CONTENT_TYPES,
    _PIL_FORMAT_TO_MIME,
    _safe_filename,
)
from .temp_byte_lease import temp_byte_lease

UPLOAD_CHUNK_BYTES: Final = 64 * 1024


@dataclass(frozen=True, slots=True)
class FileUpload:
    workspace_id: int
    filename: str
    content_type: str
    kind: Literal["image", "video", "audio"]
    max_bytes: int


@dataclass(frozen=True, slots=True)
class PreparedUpload:
    path: Path
    safe_name: str
    mime_type: str
    probe: ProbeResult


def _prepare(source: BinaryIO, path: Path, upload: FileUpload) -> PreparedUpload:
    safe_name = _safe_filename(upload.filename)
    allowed = {
        "image": _PIL_FORMAT_TO_MIME.values(),
        "video": _ALLOWED_VIDEO_CONTENT_TYPES,
        "audio": _ALLOWED_AUDIO_CONTENT_TYPES,
    }
    mime = upload.content_type.split(";", 1)[0].strip().lower()
    if mime not in allowed[upload.kind]:
        raise MediaUploadRejected(f"Unsupported {upload.kind} content type: {upload.content_type!r}")
    source.seek(0)
    total = 0
    with path.open("wb") as destination:
        while True:
            anyio.from_thread.check_cancelled()
            chunk = source.read(min(UPLOAD_CHUNK_BYTES, upload.max_bytes + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > upload.max_bytes:
                raise MediaUploadRejected("Upload exceeds maximum allowed size")
            destination.write(chunk)
    probe = probe_media_metadata(path, kind=upload.kind, max_bytes=upload.max_bytes)
    if probe.mime_type is None and upload.kind != "image":
        raise MediaUploadRejected("File content is not a recognized media file")
    return PreparedUpload(path, safe_name, probe.mime_type or mime, probe)


@asynccontextmanager
async def prepare_upload(
    source: BinaryIO, upload: FileUpload, io: BlockingIO, *, low_watermark_bytes: int = 0,
) -> AsyncIterator[PreparedUpload]:
    """Own only the staging directory; the caller retains the source stream."""
    lease = temp_byte_lease(upload.max_bytes, low_watermark_bytes)
    with anyio.CancelScope(shield=True):
        await io.run(lease.__enter__)
        temporary = await io.run(lambda: TemporaryDirectory(prefix="media-upload-"))
    try:
        yield await io.run(lambda: _prepare(source, Path(temporary.name) / "media", upload))
    finally:
        with anyio.CancelScope(shield=True):
            await io.run(temporary.cleanup)
            await io.run(lambda: lease.__exit__(None, None, None))
