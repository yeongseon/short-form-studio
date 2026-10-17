from __future__ import annotations

import io
import threading
from datetime import datetime, timedelta, timezone

import anyio
import pytest
from PIL import Image

from creator_service.media_asset_service import MediaAssetService
from creator_service.media_asset_storage import InMemoryMediaAssetStorage
from creator_service.media_upload_reconciliation import (
    MediaAssetPersistenceFailed,
    MediaAssetPersistenceIndeterminate,
    MediaUploadReconciler,
    UploadIntent,
    UploadIntentState,
)
from creator_service.object_storage import StorageDeletionError


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
            raise StorageDeletionError(key=key)
        return self.objects.pop(key, None) is not None


class _PausedObjects(_Objects):
    def __init__(self) -> None:
        super().__init__()
        self.upload_started = threading.Event()
        self.upload_allowed = threading.Event()

    def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        self.upload_started.set()
        assert self.upload_allowed.wait(timeout=5)
        return super().upload(key, data, content_type)


class _LateDeleteFailingPausedObjects(_PausedObjects):
    def delete(self, key: str) -> bool:
        if key in self.objects:
            raise StorageDeletionError(key=key)
        return False


class _FailingAssets(InMemoryMediaAssetStorage):
    def __init__(self, *, after_commit: bool = False) -> None:
        super().__init__()
        self.after_commit = after_commit

    async def save_uploaded_asset(
        self, row: dict[str, object], intent: UploadIntent,
    ) -> dict[str, object]:
        if self.after_commit:
            await super().save_uploaded_asset(row, intent)
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


@pytest.mark.asyncio
async def test_upload_losing_expired_lease_compensates_without_saving_metadata() -> None:
    # Given an upload that remains in object I/O beyond its durable lease.
    now = datetime.now(timezone.utc)
    objects = _PausedObjects()
    assets = InMemoryMediaAssetStorage()
    service = MediaAssetService(objects, assets)
    failures: list[BaseException] = []

    async def upload() -> None:
        try:
            await service.create_image_asset(
                workspace_id=7, filename="asset.png", data=_png(), content_type="image/png",
            )
        except MediaAssetPersistenceFailed as error:
            failures.append(error)

    # When reconciliation claims the expired intent before object I/O returns.
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(upload)
        await anyio.to_thread.run_sync(objects.upload_started.wait, 5)
        intent = (await assets.list_upload_intents())[0]
        await assets.expire_upload_intent(intent.id, now)
        swept = await MediaUploadReconciler(objects, assets).sweep(now=now)
        objects.upload_allowed.set()

    # Then the fenced uploader compensates and never commits live metadata.
    assert swept.reclaimed == 0
    assert len(failures) == 1
    assert objects.objects == {}
    assert (await assets.list_assets(7, limit=50, offset=0))[1] == 0


@pytest.mark.asyncio
async def test_late_upload_failed_compensation_restores_cleanup_retry() -> None:
    # Given reconciliation sees no object while its uploader remains paused.
    now = datetime.now(timezone.utc)
    objects = _LateDeleteFailingPausedObjects()
    assets = InMemoryMediaAssetStorage()
    service = MediaAssetService(objects, assets)
    failures: list[BaseException] = []

    async def upload() -> None:
        try:
            await service.create_image_asset(
                workspace_id=7, filename="asset.png", data=_png(), content_type="image/png",
            )
        except MediaAssetPersistenceFailed as error:
            failures.append(error)

    # When the sweep reclaims the absent object before upload, then late deletion fails.
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(upload)
        await anyio.to_thread.run_sync(objects.upload_started.wait, 5)
        intent = (await assets.list_upload_intents())[0]
        await assets.expire_upload_intent(intent.id, now)
        swept = await MediaUploadReconciler(objects, assets).sweep(now=now)
        objects.upload_allowed.set()

    # Then the owner restores durable cleanup ownership for a later sweep.
    assert swept.reclaimed == 0
    assert len(failures) == 1
    assert len(objects.objects) == 1
    assert (await assets.list_upload_intents())[0].state is UploadIntentState.CLEANUP_PENDING


@pytest.mark.asyncio
async def test_late_upload_after_absent_observation_is_deleted_by_later_sweep() -> None:
    # Given the first sweep observes no object after the upload operation deadline.
    now = datetime.now(timezone.utc)
    objects = _Objects()
    assets = InMemoryMediaAssetStorage()
    intent = await assets.create_upload_intent(UploadIntent(
        id=0, owner_id="terminated-uploader", workspace_id=7,
        storage_key="workspaces/7/assets/late.png",
        state=UploadIntentState.PENDING, lease_expires_at=now,
    ))
    first = await MediaUploadReconciler(objects, assets).sweep(now=now)

    # When retention elapses while absent, then the object materializes without an uploader update.
    retention = now + timedelta(hours=1)
    await assets.expire_upload_intent(intent.id, retention)
    absent = await MediaUploadReconciler(objects, assets).sweep(now=retention)
    objects.objects[intent.storage_key] = b"late upload"
    later = retention + timedelta(minutes=5)
    await assets.expire_upload_intent(intent.id, later)
    second = await MediaUploadReconciler(objects, assets).sweep(now=later)

    # Then the absent sweep retains ownership and a later sweep deletes the object.
    assert first.reclaimed == 0
    assert absent.reclaimed == 0
    assert second.reclaimed == 1
    assert objects.objects == {}
    assert (await assets.list_upload_intents())[0].state is UploadIntentState.RECLAIMED


@pytest.mark.asyncio
async def test_expired_reclaiming_claim_is_replaced_and_stale_updates_are_fenced() -> None:
    # Given a worker claim whose reconciliation lease expires before completion.
    now = datetime.now(timezone.utc)
    assets = InMemoryMediaAssetStorage()
    intent = await assets.create_upload_intent(UploadIntent(
        id=0, owner_id="uploader", workspace_id=7,
        storage_key="workspaces/7/assets/stranded.png",
        state=UploadIntentState.PENDING, lease_expires_at=now,
    ))
    first = (await assets.claim_expired_upload_intents(
        now=now, lease_expires_at=now, limit=1,
    ))[0]

    # When a successor reclaims it after expiry.
    successor = (await assets.claim_expired_upload_intents(
        now=now, lease_expires_at=now, limit=1,
    ))[0]

    # Then its token is replaced and both stale terminal/failure updates are fenced.
    assert successor.claim_token != first.claim_token
    with pytest.raises(MediaAssetPersistenceFailed):
        await assets.record_upload_reclaimed(intent.id, first.claim_token)
    with pytest.raises(MediaAssetPersistenceFailed):
        await assets.record_upload_cleanup_failure(intent.id, 5, first.claim_token)
    await assets.record_upload_reclaimed(intent.id, successor.claim_token)
