import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from creator_domain.models import MediaAsset, MediaOrigin, MediaType
from creator_service.media_asset_service import InMemoryMediaAssetStorage, MediaAssetService
from creator_service.object_storage import LocalStorageBackend
from PIL import Image


@pytest.mark.asyncio
async def test_uploaded_annotations_preserve_bytes_and_cannot_override_owned_facts(tmp_path: Path) -> None:
    # Given synthetic bytes and annotations attempting to forge every domain field.
    backend = LocalStorageBackend(str(tmp_path))
    service = MediaAssetService(backend, InMemoryMediaAssetStorage())
    with BytesIO() as buffer, Image.new("RGB", (18, 32), (24, 192, 208)) as image:
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
    metadata = dict.fromkeys(MediaAsset.model_fields, "forged") | {
        "asset_path": "/secret", "size_bytes": "0", "checksum": "forged",
        "storage_provider": "s3", "original_filename": "../secret",
        "license": "CC0-1.0", "provenance": "synthetic", "example_role": "uploaded-example",
    }
    original_metadata = metadata.copy()

    # When the public upload contract persists caller annotations.
    asset = await service.create_image_asset(
        workspace_id=7, project_id=3, run_id=5, filename="uploaded-example.png",
        data=data, content_type="image/png", metadata=metadata,
    )

    # Then annotations survive, while trusted ownership, provenance and storage facts win.
    assert asset.origin is MediaOrigin.UPLOADED
    assert asset.media_type is MediaType.IMAGE
    assert (asset.workspace_id, asset.project_id, asset.run_id) == (7, 3, 5)
    assert (asset.width, asset.height, asset.mime_type, asset.duration_seconds) == (18, 32, "image/png", None)
    assert asset.source_url is None
    assert asset.storage_key is not None and asset.storage_key.startswith("workspaces/7/assets/")
    assert asset.metadata == {
        "license": "CC0-1.0", "provenance": "synthetic", "example_role": "uploaded-example",
        "size_bytes": len(data), "checksum": hashlib.md5(data, usedforsecurity=False).hexdigest(),
        "storage_provider": "local", "original_filename": "uploaded-example.png",
    }
    assert backend.download_bytes(asset.storage_key) == data
    assert await service.get_asset(asset.id, 7) == asset
    assert await service.get_asset(asset.id, 8) is None
    assert metadata == original_metadata
