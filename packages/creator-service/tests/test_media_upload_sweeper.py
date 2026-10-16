from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from creator_service.media_asset_storage import InMemoryMediaAssetStorage
from creator_service.media_asset_service import MediaAssetService
from creator_service.media_upload_reconciliation import (
    MediaUploadReconciler,
    UploadIntent,
    UploadIntentState,
)
from creator_service.object_storage import StorageDeletionError


class _Objects:
    def __init__(self, *, fail_delete: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_delete = fail_delete

    def delete(self, key: str) -> bool:
        if self.fail_delete:
            raise StorageDeletionError(key=key)
        return self.objects.pop(key, None) is not None

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        self.objects[key] = data

        class Result:
            size_bytes = len(data)
            checksum = "checksum"
            storage_provider = "memory"

            def __init__(self, result_key: str, result_type: str) -> None:
                self.key = result_key
                self.content_type = result_type

        return Result(key, content_type)


async def _intent(
    storage: InMemoryMediaAssetStorage, *, workspace_id: int, key: str, now: datetime,
) -> UploadIntent:
    return await storage.create_upload_intent(UploadIntent(
        id=0, owner_id=key, workspace_id=workspace_id, storage_key=key,
        state=UploadIntentState.UPLOADED, lease_expires_at=now - timedelta(seconds=1),
    ))


@pytest.mark.asyncio
async def test_sweeper_reclaims_only_expired_unregistered_owned_key() -> None:
    # Given crashed and completed attempts owned by separate workspaces.
    now = datetime.now(timezone.utc)
    objects = _Objects()
    storage = InMemoryMediaAssetStorage()
    crashed = await _intent(storage, workspace_id=7, key="workspaces/7/assets/crashed.png", now=now)
    completed = await _intent(storage, workspace_id=9, key="workspaces/9/assets/good.png", now=now)
    await storage.complete_upload_intent(completed.id, owner_id=completed.owner_id)
    objects.objects = {crashed.storage_key: b"orphan", completed.storage_key: b"live"}

    # When a reconciliation pass leases expired work.
    result = await MediaUploadReconciler(objects, storage).sweep(now=now)

    # Then only the exact orphan is reclaimed.
    assert result.reclaimed == 1
    assert objects.objects == {completed.storage_key: b"live"}


@pytest.mark.asyncio
async def test_duplicate_sweepers_claim_an_orphan_once() -> None:
    # Given one expired orphan intent.
    now = datetime.now(timezone.utc)
    objects = _Objects()
    storage = InMemoryMediaAssetStorage()
    orphan = await _intent(storage, workspace_id=7, key="workspaces/7/assets/orphan.png", now=now)
    objects.objects[orphan.storage_key] = b"orphan"

    # When duplicate sweep passes run.
    first = await MediaUploadReconciler(objects, storage).sweep(now=now)
    second = await MediaUploadReconciler(objects, storage).sweep(now=now)

    # Then the object is reclaimed once and both passes converge.
    assert (first.reclaimed, second.reclaimed) == (1, 0)
    assert objects.objects == {}


@pytest.mark.asyncio
async def test_sweeper_preserves_registered_timeline_eligible_media() -> None:
    # Given persisted media whose stale intent incorrectly appears reclaimable.
    from io import BytesIO

    from PIL import Image

    with BytesIO() as buffer:
        Image.new("RGB", (4, 6)).save(buffer, format="PNG")
        payload = buffer.getvalue()
    now = datetime.now(timezone.utc)
    objects = _Objects()
    storage = InMemoryMediaAssetStorage()
    asset = await MediaAssetService(objects, storage).create_image_asset(
        workspace_id=7, filename="timeline.png", data=payload, content_type="image/png",
    )
    stale = await _intent(
        storage, workspace_id=7, key=asset.storage_key or "", now=now,
    )

    # When reconciliation verifies registration by the exact workspace key.
    result = await MediaUploadReconciler(objects, storage).sweep(now=now)

    # Then media available for Timeline references remains intact and completed.
    assert result.preserved == 1
    assert asset.storage_key in objects.objects
    intents = await storage.list_upload_intents()
    assert next(intent for intent in intents if intent.id == stale.id).state is UploadIntentState.COMPLETED


@pytest.mark.asyncio
async def test_sweeper_bounds_delete_retries() -> None:
    # Given an orphan whose backend deletion always fails.
    now = datetime.now(timezone.utc)
    objects = _Objects(fail_delete=True)
    storage = InMemoryMediaAssetStorage()
    orphan = await _intent(storage, workspace_id=7, key="workspaces/7/assets/orphan.png", now=now)
    objects.objects[orphan.storage_key] = b"orphan"
    reconciler = MediaUploadReconciler(objects, storage, max_retries=2)

    # When retry leases expire twice.
    await reconciler.sweep(now=now)
    await storage.expire_upload_intent(orphan.id, now)
    await reconciler.sweep(now=now)

    # Then the durable record is exhausted and retained for operator action.
    stored = (await storage.list_upload_intents())[0]
    assert stored.state is UploadIntentState.EXHAUSTED
    assert stored.retry_count == 2
