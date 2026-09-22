from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from pathlib import Path

import pytest
from creator_domain.models import MediaOrigin, MediaType
from creator_service.media_asset_service import (
    InMemoryMediaAssetStorage,
    MediaAssetService,
    MediaUploadRejected,
    _create_service,
)
from creator_service.object_storage import LocalStorageBackend
from creator_service.postgres_media_asset_storage import PostgresMediaAssetStorage
from PIL import Image


def image_bytes(fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 12), (20, 40, 60)).save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.mark.parametrize("factory", [MediaAssetService, _create_service])
def test_database_url_selects_postgres(
    monkeypatch: pytest.MonkeyPatch, factory: Callable[[], MediaAssetService],
) -> None:
    # Given a configured deployment, without opening a database connection.
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/selection_only")
    # When constructing through either public or module factory path.
    service = factory()
    # Then metadata must not silently remain process-local.
    assert isinstance(service._asset_storage, PostgresMediaAssetStorage)


def test_explicit_storage_overrides_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a configured deployment with an explicitly injected adapter.
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/selection_only")
    storage = InMemoryMediaAssetStorage()
    # When constructing the service.
    service = MediaAssetService(asset_storage=storage)
    # Then dependency injection remains supported.
    assert service._asset_storage is storage


@pytest.mark.asyncio
async def test_generated_png_preserves_bytes_and_provenance(tmp_path: Path) -> None:
    # Given real PNG bytes and the existing object storage API.
    backend = LocalStorageBackend(str(tmp_path))
    service = MediaAssetService(backend, InMemoryMediaAssetStorage())
    data = image_bytes()
    # When storing through the public generated-image contract.
    asset = await service.create_generated_image_asset(
        workspace_id=7, project_id=3, filename="sample.png", data=data,
        metadata={"demo": True, "nested": {"label": "샘플"}},
    )
    # Then both byte identity and generated provenance survive a scoped read.
    assert asset.origin is MediaOrigin.GENERATED
    assert asset.media_type is MediaType.IMAGE
    assert (asset.width, asset.height, asset.mime_type) == (8, 12, "image/png")
    assert (asset.workspace_id, asset.project_id, asset.run_id) == (7, 3, None)
    assert asset.storage_key is not None
    assert asset.storage_key.startswith("workspaces/7/assets/")
    assert backend.download_bytes(asset.storage_key) == data
    assert await service.get_asset(asset.id, 7) == asset
    assert await service.get_asset(asset.id, 8) is None
    assert asset.metadata["nested"] == {"label": "샘플"}


@pytest.mark.asyncio
async def test_generated_metadata_cannot_override_owned_fields(tmp_path: Path) -> None:
    # Given caller metadata attempting to replace security and storage fields.
    service = MediaAssetService(LocalStorageBackend(str(tmp_path)), InMemoryMediaAssetStorage())
    data = image_bytes()
    metadata: dict[str, object] = {
        "checksum": "forged", "size_bytes": 0, "storage_provider": "s3",
        "original_filename": "../secret", "workspace_id": 99, "project_id": 99,
        "storage_key": "../secret", "origin": "uploaded", "asset_path": "/secret",
        "demo": True,
    }
    # When the generated image is saved.
    asset = await service.create_generated_image_asset(
        workspace_id=7, project_id=3, filename="sample.png", data=data, metadata=metadata,
    )
    # Then only caller-owned annotations merge, while storage facts remain authoritative.
    assert asset.metadata == {
        "checksum": hashlib.md5(data, usedforsecurity=False).hexdigest(),
        "size_bytes": len(data), "storage_provider": "local",
        "original_filename": "sample.png", "demo": True,
    }
    assert metadata["checksum"] == "forged"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data", [b"", b"not an image", image_bytes("JPEG"), image_bytes()[:40]],
    ids=["empty", "invalid", "jpeg", "truncated"],
)
async def test_generated_image_rejects_invalid_png_before_writing(tmp_path: Path, data: bytes) -> None:
    # Given invalid, truncated, or non-PNG content.
    service = MediaAssetService(LocalStorageBackend(str(tmp_path)), InMemoryMediaAssetStorage())
    # When creating a generated PNG.
    with pytest.raises(MediaUploadRejected):
        await service.create_generated_image_asset(
            workspace_id=7, project_id=3, filename="sample.png", data=data,
        )
    # Then neither bytes nor metadata have been saved.
    assert list(tmp_path.iterdir()) == []
    assert (await service.list_assets(workspace_id=7)).total == 0


@pytest.mark.asyncio
async def test_database_failure_propagates_without_memory_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from creator_service import db

    # Given a configured metadata database whose connection fails.
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused/selection_only")

    async def unavailable() -> None:
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(db, "get_pool", unavailable)
    # When reading metadata.
    with pytest.raises(ConnectionError, match="database unavailable"):
        await MediaAssetService().get_asset(1, 7)
    # Then the configured backend remains Postgres.
    assert isinstance(MediaAssetService()._asset_storage, PostgresMediaAssetStorage)


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["../escape.png", "/tmp/escape.png", "a\\b.png", ""])
async def test_generated_image_rejects_unsafe_filename(tmp_path: Path, filename: str) -> None:
    # Given a filename outside the single-component filename contract.
    service = MediaAssetService(LocalStorageBackend(str(tmp_path)), InMemoryMediaAssetStorage())
    # When creating the image.
    with pytest.raises(MediaUploadRejected):
        await service.create_generated_image_asset(
            workspace_id=7, project_id=3, filename=filename, data=image_bytes(),
        )
    # Then validation precedes any artifact write.
    assert list(tmp_path.iterdir()) == []
