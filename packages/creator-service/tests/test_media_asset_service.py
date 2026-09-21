from __future__ import annotations

import io

import pytest
from creator_domain.models import MediaAsset, MediaOrigin, MediaType
from creator_service.media_asset_service import (
    MediaAssetService,
    MediaUploadRejected,
    _probe_image_dimensions,
    _validate_image_upload,
)
from PIL import Image


def _png_bytes(width: int = 4, height: int = 6, color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


class _RecordingStorage:
    """Records upload calls and returns a deterministic storage result."""

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


# --- validation --------------------------------------------------------------


def test_validate_rejects_non_image_content_type() -> None:
    with pytest.raises(MediaUploadRejected):
        _validate_image_upload(_png_bytes(), content_type="text/plain")


def test_validate_rejects_empty_payload() -> None:
    with pytest.raises(MediaUploadRejected):
        _validate_image_upload(b"", content_type="image/png")


def test_validate_rejects_oversized_payload() -> None:
    with pytest.raises(MediaUploadRejected):
        _validate_image_upload(
            b"x" * 10, content_type="image/png", max_bytes=5
        )


def test_validate_rejects_spoofed_image_bytes() -> None:
    # Declared image/png but the bytes are not a real image.
    with pytest.raises(MediaUploadRejected):
        _validate_image_upload(b"not-an-image", content_type="image/png")


def test_validate_accepts_real_png() -> None:
    # Should not raise.
    _validate_image_upload(_png_bytes(), content_type="image/png")


def test_probe_image_dimensions_returns_width_height() -> None:
    width, height = _probe_image_dimensions(_png_bytes(width=12, height=34))
    assert (width, height) == (12, 34)


# --- service create ----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_image_asset_uploads_and_returns_media_asset() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)
    data = _png_bytes(width=8, height=16)

    asset = await service.create_image_asset(
        workspace_id=1,
        filename="hero.png",
        data=data,
        content_type="image/png",
        project_id=3,
    )

    assert isinstance(asset, MediaAsset)
    assert asset.workspace_id == 1
    assert asset.project_id == 3
    assert asset.media_type is MediaType.IMAGE
    assert asset.origin is MediaOrigin.UPLOADED
    assert asset.mime_type == "image/png"
    assert asset.width == 8
    assert asset.height == 16
    assert asset.storage_key is not None
    assert asset.metadata.get("size_bytes") == len(data)
    # exactly one upload recorded, under the workspace-scoped key
    assert len(storage.uploads) == 1
    key, payload, ctype = storage.uploads[0]
    assert key.startswith("workspaces/1/assets/")
    assert payload == data
    assert ctype == "image/png"


@pytest.mark.asyncio
async def test_create_image_asset_scopes_storage_key_to_workspace() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)

    asset_a = await service.create_image_asset(
        workspace_id=7, filename="a.png", data=_png_bytes(), content_type="image/png"
    )
    asset_b = await service.create_image_asset(
        workspace_id=9, filename="a.png", data=_png_bytes(), content_type="image/png"
    )

    assert asset_a.storage_key is not None and asset_a.storage_key.startswith("workspaces/7/assets/")
    assert asset_b.storage_key is not None and asset_b.storage_key.startswith("workspaces/9/assets/")
    assert asset_a.storage_key != asset_b.storage_key
    assert asset_a.id != asset_b.id


@pytest.mark.asyncio
async def test_create_image_asset_rejects_spoofed_bytes_without_upload() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)

    with pytest.raises(MediaUploadRejected):
        await service.create_image_asset(
            workspace_id=1,
            filename="x.png",
            data=b"not-an-image",
            content_type="image/png",
        )
    # No partial upload on rejection.
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_create_image_asset_rejects_unsafe_filename() -> None:
    storage = _RecordingStorage()
    service = MediaAssetService(storage_backend=storage)

    with pytest.raises(MediaUploadRejected):
        await service.create_image_asset(
            workspace_id=1,
            filename="../../etc/passwd",
            data=_png_bytes(),
            content_type="image/png",
        )
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_get_asset_returns_persisted_asset() -> None:
    service = MediaAssetService(storage_backend=_RecordingStorage())
    created = await service.create_image_asset(
        workspace_id=2, filename="a.png", data=_png_bytes(), content_type="image/png"
    )

    fetched = await service.get_asset(created.id, workspace_id=2)
    assert fetched is not None
    assert fetched.id == created.id


@pytest.mark.asyncio
async def test_get_asset_enforces_workspace_isolation() -> None:
    service = MediaAssetService(storage_backend=_RecordingStorage())
    created = await service.create_image_asset(
        workspace_id=2, filename="a.png", data=_png_bytes(), content_type="image/png"
    )

    # Cross-workspace lookup must not leak the asset (anti-enumeration).
    assert await service.get_asset(created.id, workspace_id=999) is None
