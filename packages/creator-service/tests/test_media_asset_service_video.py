from __future__ import annotations

import subprocess

import pytest
from creator_domain.models import MediaAsset, MediaOrigin, MediaType
from creator_service.media_asset_service import (
    MediaAssetService,
    MediaUploadRejected,
    _probe_media_metadata,
)


def _make_video_bytes(seconds: float = 1.0, width: int = 64, height: int = 48) -> bytes:
    """Build a tiny real MP4 with ffmpeg so ffprobe can read it."""
    import shutil
    import tempfile
    from pathlib import Path

    if shutil.which("ffmpeg") is None:  # pragma: no cover - env guard
        pytest.skip("ffmpeg not available")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "v.mp4"
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi",
            "-i", f"color=c=blue:s={width}x{height}:d={seconds}",
            "-pix_fmt", "yuv420p",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0 or not out.exists():  # pragma: no cover - env guard
            pytest.skip("ffmpeg could not produce a test video")
        return out.read_bytes()


class _RecordingStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str]] = []

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        payload = data if isinstance(data, bytes) else data.read()
        self.uploads.append((key, payload, content_type))

        class _Result:
            def __init__(self, key: str, size: int, content_type: str) -> None:
                self.key = key
                self.size_bytes = size
                self.content_type = content_type
                self.checksum = "deadbeef"
                self.storage_provider = "local"

        return _Result(key, len(payload), content_type)


# --- probe -------------------------------------------------------------------


def test_probe_media_metadata_reads_video_dimensions_and_duration() -> None:
    data = _make_video_bytes(seconds=1.0, width=48, height=32)
    meta = _probe_media_metadata(data, kind="video")

    assert meta.width == 48
    assert meta.height == 32
    assert meta.duration_seconds is not None
    assert meta.duration_seconds > 0


def test_probe_media_metadata_rejects_non_media_bytes() -> None:
    with pytest.raises(MediaUploadRejected):
        _probe_media_metadata(b"not-a-video", kind="video")


# --- service create_video_asset ----------------------------------------------


@pytest.mark.asyncio
async def test_create_video_asset_uploads_and_returns_media_asset() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)
    data = _make_video_bytes(seconds=1.0, width=64, height=48)

    asset = await service.create_video_asset(
        workspace_id=1,
        filename="clip.mp4",
        data=data,
        content_type="video/mp4",
        project_id=2,
    )

    assert isinstance(asset, MediaAsset)
    assert asset.workspace_id == 1
    assert asset.project_id == 2
    assert asset.media_type is MediaType.VIDEO
    assert asset.origin is MediaOrigin.UPLOADED
    assert asset.mime_type == "video/mp4"
    assert asset.width == 64
    assert asset.height == 48
    assert asset.duration_seconds is not None and asset.duration_seconds > 0
    assert asset.storage_key is not None and asset.storage_key.startswith("workspaces/1/assets/")
    assert asset.metadata.get("size_bytes") == len(data)
    # source-preserving: the exact uploaded bytes are stored unchanged
    assert len(storage.uploads) == 1
    key, payload, ctype = storage.uploads[0]
    assert payload == data
    assert ctype == "video/mp4"


@pytest.mark.asyncio
async def test_create_video_asset_rejects_unsupported_content_type() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)

    with pytest.raises(MediaUploadRejected):
        await service.create_video_asset(
            workspace_id=1,
            filename="clip.mov",
            data=b"anything",
            content_type="application/octet-stream",
        )
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_create_video_asset_rejects_spoofed_bytes_without_upload() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)

    with pytest.raises(MediaUploadRejected):
        await service.create_video_asset(
            workspace_id=1,
            filename="clip.mp4",
            data=b"not-a-video",
            content_type="video/mp4",
        )
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_create_video_asset_rejects_oversized_payload() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)

    with pytest.raises(MediaUploadRejected):
        await service.create_video_asset(
            workspace_id=1,
            filename="clip.mp4",
            data=b"x" * 100,
            content_type="video/mp4",
            max_bytes=10,
        )
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_create_video_asset_rejects_unsafe_filename() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)
    data = _make_video_bytes()

    with pytest.raises(MediaUploadRejected):
        await service.create_video_asset(
            workspace_id=1,
            filename="../../etc/passwd",
            data=data,
            content_type="video/mp4",
        )
    assert storage.uploads == []
