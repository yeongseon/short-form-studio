from __future__ import annotations

from datetime import datetime, timedelta, timezone

import anyio
import pytest

from creator_service.media_asset_storage import InMemoryMediaAssetStorage
from creator_service.media_upload_reconciliation import UploadIntent, UploadIntentState
from creator_service.storage_policy import StorageBudgetExceeded, StoragePolicy
from creator_service.storage_policy import StorageLowWatermark


def _intent(owner: str, reserved_bytes: int) -> UploadIntent:
    return UploadIntent(
        id=0,
        owner_id=owner,
        workspace_id=7,
        storage_key=f"workspaces/7/assets/{owner}.png",
        state=UploadIntentState.PENDING,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        reserved_bytes=reserved_bytes,
    )


@pytest.mark.anyio
async def test_concurrent_admission_never_overbooks_workspace_bytes() -> None:
    # Given two uploads racing for the same remaining capacity.
    storage = InMemoryMediaAssetStorage()
    policy = StoragePolicy(max_stored_bytes=10, max_asset_count=10, max_reserved_bytes=10)
    ready = anyio.Event()
    results: list[str] = []

    async def reserve(owner: str) -> None:
        await ready.wait()
        try:
            await storage.create_upload_intent(_intent(owner, 6), policy=policy)
        except StorageBudgetExceeded:
            results.append("rejected")
        else:
            results.append("reserved")

    # When both attempts pass a barrier together.
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(reserve, "one")
        tasks.start_soon(reserve, "two")
        ready.set()

    # Then one reservation wins atomically and the other is rejected.
    assert sorted(results) == ["rejected", "reserved"]
    usage = await storage.get_storage_usage(7, policy=policy)
    assert usage.reserved_bytes == 6
    assert usage.reserved_asset_count == 1


@pytest.mark.anyio
async def test_reclaim_releases_only_its_reservation_once() -> None:
    storage = InMemoryMediaAssetStorage()
    policy = StoragePolicy(max_stored_bytes=20, max_asset_count=2, max_reserved_bytes=20)
    first = await storage.create_upload_intent(_intent("one", 6), policy=policy)
    await storage.create_upload_intent(_intent("two", 7), policy=policy)

    await storage.record_upload_reclaimed(first.id)
    await storage.record_upload_reclaimed(first.id)

    usage = await storage.get_storage_usage(7, policy=policy)
    assert usage.reserved_bytes == 7
    assert usage.reserved_asset_count == 1


@pytest.mark.anyio
async def test_cleanup_pending_retains_capacity_until_object_delete_succeeds() -> None:
    storage = InMemoryMediaAssetStorage()
    policy = StoragePolicy(max_stored_bytes=10, max_asset_count=1, max_reserved_bytes=10)
    intent = await storage.create_upload_intent(_intent("one", 10), policy=policy)
    await storage.compensate_upload(intent, deletion_failed=True)

    with pytest.raises(StorageBudgetExceeded):
        await storage.create_upload_intent(_intent("two", 1), policy=policy)

    usage = await storage.get_storage_usage(7, policy=policy)
    assert usage.reserved_bytes == 10


@pytest.mark.anyio
async def test_crash_sweep_retains_capacity_until_reclamation_finishes() -> None:
    # Given an expired reservation whose uploader may still materialize its object.
    storage = InMemoryMediaAssetStorage()
    policy = StoragePolicy(max_stored_bytes=10, max_asset_count=1, max_reserved_bytes=10)
    intent = await storage.create_upload_intent(_intent("one", 10), policy=policy)

    # When the crash sweeper claims ownership but has not completed cleanup.
    claimed = await storage.claim_expired_upload_intents(
        now=intent.lease_expires_at,
        lease_expires_at=intent.lease_expires_at + timedelta(minutes=5),
        limit=1,
    )

    # Then admission remains blocked until the owned reclamation is terminal.
    with pytest.raises(StorageBudgetExceeded):
        await storage.create_upload_intent(_intent("two", 1), policy=policy)
    await storage.record_upload_reclaimed(intent.id, claimed[0].claim_token)
    replacement = await storage.create_upload_intent(_intent("two", 1), policy=policy)
    assert replacement.reserved_bytes == 1


def test_temp_low_watermark_blocks_new_writes(monkeypatch) -> None:
    policy = StoragePolicy(temp_disk_low_watermark_bytes=100)
    usage = type("DiskUsage", (), {"free": 109})()
    monkeypatch.setattr("creator_service.storage_policy.shutil.disk_usage", lambda _: usage)

    with pytest.raises(StorageLowWatermark):
        policy.ensure_temp_capacity(10)
