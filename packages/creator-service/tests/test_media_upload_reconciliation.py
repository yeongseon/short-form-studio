from __future__ import annotations

import io
import pytest
from PIL import Image

from creator_service.media_asset_service import MediaAssetService
from creator_service.media_asset_storage import InMemoryMediaAssetStorage
from creator_service.media_upload_reconciliation import (
    MediaAssetPersistenceFailed,
    MediaAssetPersistenceIndeterminate,
    UploadIntentState,
)


def _png() -> bytes:
    with io.BytesIO() as buffer:
        Image.new("RGB", (4, 6)).save(buffer, format="PNG")
        return buffer.getvalue()


class _Objects:
    def __init__(self, *, fail_delete: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_delete = fail_delete

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        payload = data if isinstance(data, bytes) else data.read()
        self.objects[key] = payload

        class Result:
            size_bytes = len(payload)
            checksum = "checksum"
            storage_provider = "memory"

            def __init__(self, result_key: str, result_type: str) -> None:
                self.key = result_key
                self.content_type = result_type

        return Result(key, content_type)

    def delete(self, key: str) -> bool:
        if self.fail_delete:
            raise OSError("delete unavailable")
        return self.objects.pop(key, None) is not None


class _FailingAssets(InMemoryMediaAssetStorage):
    def __init__(self, *, after_commit: bool = False) -> None:
        super().__init__()
        self.after_commit = after_commit

    async def save_asset(self, row: dict[str, object]) -> dict[str, object]:
        if self.after_commit:
            await super().save_asset(row)
            raise MediaAssetPersistenceIndeterminate()
        raise MediaAssetPersistenceFailed()


@pytest.mark.asyncio
async def test_definite_metadata_failure_compensates_uploaded_object() -> None:
    # Given an upload backend and metadata persistence that definitely rejects.
    objects = _Objects()
    assets = _FailingAssets()
    service = MediaAssetService(objects, assets)

    # When metadata persistence fails after the object upload.
    with pytest.raises(MediaAssetPersistenceFailed):
        await service.create_image_asset(
            workspace_id=7, filename="asset.png", data=_png(), content_type="image/png",
        )

    # Then the object is deleted and its durable intent reaches a terminal state.
    assert objects.objects == {}
    assert (await assets.list_upload_intents())[0].state is UploadIntentState.RECLAIMED


@pytest.mark.asyncio
async def test_ambiguous_commit_preserves_registered_object() -> None:
    # Given a save that commits metadata before losing its acknowledgement.
    objects = _Objects()
    assets = _FailingAssets(after_commit=True)
    service = MediaAssetService(objects, assets)

    # When the caller receives an indeterminate persistence outcome.
    with pytest.raises(MediaAssetPersistenceIndeterminate):
        await service.create_image_asset(
            workspace_id=7, filename="asset.png", data=_png(), content_type="image/png",
        )

    # Then registration is verified by key and the live object is never deleted.
    assert len(objects.objects) == 1
    assert (await assets.list_upload_intents())[0].state is UploadIntentState.COMPLETED
    assert (await assets.list_assets(7, limit=50, offset=0))[1] == 1


@pytest.mark.asyncio
async def test_cleanup_failure_remains_retryable() -> None:
    # Given compensation whose object deletion is temporarily unavailable.
    objects = _Objects(fail_delete=True)
    assets = _FailingAssets()
    service = MediaAssetService(objects, assets)

    # When metadata persistence definitely fails.
    with pytest.raises(MediaAssetPersistenceFailed):
        await service.create_image_asset(
            workspace_id=7, filename="asset.png", data=_png(), content_type="image/png",
        )

    # Then ownership is retained in a durable retry state.
    assert len(objects.objects) == 1
    assert (await assets.list_upload_intents())[0].state is UploadIntentState.CLEANUP_PENDING
