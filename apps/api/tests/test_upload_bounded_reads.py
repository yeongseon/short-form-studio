import io
from pathlib import Path
from typing import Callable, Awaitable

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers
from PIL import Image
from creator_domain.exceptions import ValidationError
from creator_service.media_asset_service import MediaAssetService, InMemoryMediaAssetStorage
from creator_service.object_storage import LocalStorageBackend
from shorts_api.auth import CurrentUser
from shorts_api.routes import creator_assets


class BoundedReader(io.BytesIO):
    """Real seekable stream recording reads, without accepting a huge allocation."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.requests: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requests.append(size)
        assert 0 < size <= 64 * 1024, f"unbounded read: {size}"
        return super().read(size)


@pytest.mark.asyncio
@pytest.mark.parametrize("route,mime", [
    (creator_assets.upload_image_asset, "image/png"),
    (creator_assets.upload_video_asset, "video/mp4"),
    (creator_assets.upload_audio_asset, "audio/wav"),
])
async def test_route_never_requests_limit_sized_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    route: Callable[..., Awaitable[dict[str, object]]], mime: str,
) -> None:
    # Given the real UploadFile wrapper and an intentionally small cap.
    for cap in ("_MAX_IMAGE_BYTES", "_MAX_VIDEO_BYTES", "_MAX_AUDIO_BYTES"):
        monkeypatch.setattr(creator_assets, cap, 131072)
    service = MediaAssetService(LocalStorageBackend(str(tmp_path)), InMemoryMediaAssetStorage())
    monkeypatch.setattr(creator_assets, "media_asset_service", service)
    with BoundedReader(b"x" * 200000) as source:
        upload = UploadFile(source, filename="media", headers=Headers({"content-type": mime}))
        # When an oversize payload reaches the route.
        with pytest.raises(ValidationError):
            await route(workspace_id=7, file=upload, user=CurrentUser(user_id=1, workspace_id=7))
        # Then only limit+1 bytes were consumed and no object was stored.
        assert source.tell() == 131073
        assert max(source.requests) <= 65536
    assert not list(tmp_path.rglob("*"))


@pytest.mark.asyncio
async def test_route_rewinds_real_upload_and_preserves_image_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a real image, caller position at EOF, and a supported but inaccurate MIME.
    image = io.BytesIO()
    Image.new("RGB", (8, 12)).save(image, format="PNG")
    data = image.getvalue()
    backend = LocalStorageBackend(str(tmp_path))
    monkeypatch.setattr(creator_assets, "media_asset_service", MediaAssetService(backend, InMemoryMediaAssetStorage()))
    with BoundedReader(data) as source:
        source.seek(0, 2)
        upload = UploadFile(source, filename="image.jpg", headers=Headers({"content-type": "image/jpeg"}))
        # When ingested through the actual route.
        asset = await creator_assets.upload_image_asset(7, upload, CurrentUser(user_id=1, workspace_id=7))
        # Then actual bytes, rather than supplied MIME/position, govern storage.
        assert asset["mime_type"] == "image/png"
        assert not source.closed
    key = asset["storage_key"]
    assert isinstance(key, str)
    assert backend.download_bytes(key) == data
