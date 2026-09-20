from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from creator_domain.models import MediaAsset, MediaOrigin, MediaType
from creator_service.media_asset_service import (
    MediaAssetService,
    MediaUploadRejected,
)


def _make_audio_bytes(seconds: float = 1.0) -> bytes:
    if shutil.which("ffmpeg") is None:  # pragma: no cover - env guard
        pytest.skip("ffmpeg not available")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "a.mp3"
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={seconds}",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0 or not out.exists():  # pragma: no cover - env guard
            pytest.skip("ffmpeg could not produce a test audio file")
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


@pytest.mark.asyncio
async def test_create_audio_asset_uploads_and_returns_media_asset() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)
    data = _make_audio_bytes(seconds=1.0)

    asset = await service.create_audio_asset(
        workspace_id=1,
        filename="voice.mp3",
        data=data,
        content_type="audio/mpeg",
        project_id=4,
    )

    assert isinstance(asset, MediaAsset)
    assert asset.workspace_id == 1
    assert asset.project_id == 4
    assert asset.media_type is MediaType.AUDIO
    assert asset.origin is MediaOrigin.UPLOADED
    assert asset.mime_type == "audio/mpeg"
    assert asset.width is None
    assert asset.height is None
    assert asset.duration_seconds is not None and asset.duration_seconds > 0
    assert asset.storage_key is not None and asset.storage_key.startswith("workspaces/1/assets/")
    assert asset.metadata.get("size_bytes") == len(data)
    assert len(storage.uploads) == 1
    key, payload, ctype = storage.uploads[0]
    assert payload == data
    assert ctype == "audio/mpeg"


@pytest.mark.asyncio
async def test_create_audio_asset_rejects_unsupported_content_type() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)

    with pytest.raises(MediaUploadRejected):
        await service.create_audio_asset(
            workspace_id=1,
            filename="voice.aiff",
            data=b"anything",
            content_type="application/octet-stream",
        )
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_create_audio_asset_rejects_spoofed_bytes_without_upload() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)

    with pytest.raises(MediaUploadRejected):
        await service.create_audio_asset(
            workspace_id=1,
            filename="voice.mp3",
            data=b"not-audio",
            content_type="audio/mpeg",
        )
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_create_audio_asset_rejects_oversized_payload() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)

    with pytest.raises(MediaUploadRejected):
        await service.create_audio_asset(
            workspace_id=1,
            filename="voice.mp3",
            data=b"x" * 100,
            content_type="audio/mpeg",
            max_bytes=10,
        )
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_create_audio_asset_rejects_unsafe_filename() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)
    data = _make_audio_bytes()

    with pytest.raises(MediaUploadRejected):
        await service.create_audio_asset(
            workspace_id=1,
            filename="../../etc/passwd",
            data=data,
            content_type="audio/mpeg",
        )
    assert storage.uploads == []
