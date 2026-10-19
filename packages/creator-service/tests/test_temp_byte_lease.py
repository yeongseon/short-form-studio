from __future__ import annotations

import tempfile
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, get_ident

import anyio
import pytest
from PIL import Image

from creator_service.media_asset_service import MediaAssetService
from creator_service.media_asset_storage import InMemoryMediaAssetStorage
from creator_service.media_file_ingestion import FileUpload
from creator_service.object_storage import LocalStorageBackend
from creator_service.storage_policy import StoragePolicy
from creator_service.storage_policy import StorageLowWatermark
from creator_service.temp_byte_lease import temp_byte_lease


def test_shared_byte_lease_allows_only_one_concurrent_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given two workers share the same staging volume with room for one lease.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    disk_usage = type("DiskUsage", (), {"free": 100})()
    monkeypatch.setattr("creator_service.temp_byte_lease.shutil.disk_usage", lambda _: disk_usage)
    barrier = Barrier(2)
    release = Event()

    def acquire() -> str:
        barrier.wait()
        try:
            with temp_byte_lease(60, 20):
                release.wait(2)
                return "accepted"
        except StorageLowWatermark:
            release.set()
            return "rejected"

    # When both workers acquire against the shared lease ledger concurrently.
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _: acquire(), range(2)))

    # Then one is rejected and all lease files are released.
    assert results == ["accepted", "rejected"]
    assert list((tmp_path / ".media-byte-leases").glob("*.lease")) == []


@pytest.mark.asyncio
async def test_concurrent_staging_rejects_one_and_preserves_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given two uploads share constrained staging while the first writer is paused.
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(staging))
    disk_usage = type("DiskUsage", (), {"free": 1500})()
    monkeypatch.setattr("creator_service.temp_byte_lease.shutil.disk_usage", lambda _: disk_usage)
    payload_buffer = io.BytesIO()
    Image.new("RGB", (8, 12)).save(payload_buffer, format="PNG")
    payload = payload_buffer.getvalue()
    entered = anyio.Event()
    release = Event()
    event_thread = get_ident()

    class PausedSource(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert get_ident() != event_thread
            anyio.from_thread.run_sync(entered.set)
            assert release.wait(5)
            return super().read(size)

    backend = LocalStorageBackend(str(tmp_path / "objects"))
    service = MediaAssetService(
        backend, InMemoryMediaAssetStorage(),
        StoragePolicy(temp_disk_low_watermark_bytes=400),
    )
    outcomes: list[str] = []

    async def first_upload() -> None:
        with PausedSource(payload) as source:
            await service.create_file_asset(
                source, FileUpload(7, "first.png", "image/png", "image", 1000),
            )
        outcomes.append("accepted")

    # When both uploads overlap before the first staging lease is released.
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(first_upload)
        await entered.wait()
        with io.BytesIO(payload) as source, pytest.raises(StorageLowWatermark):
            await service.create_file_asset(
                source, FileUpload(7, "second.png", "image/png", "image", 1000),
            )
        outcomes.append("rejected")
        release.set()

    # Then staging is clean and the accepted asset remains readable.
    page = await service.list_assets(workspace_id=7)
    assert sorted(outcomes) == ["accepted", "rejected"]
    assert [path.name for path in staging.iterdir()] == [".media-byte-leases"]
    assert len(page.items) == 1
    assert backend.download_bytes(page.items[0].storage_key or "") == payload
