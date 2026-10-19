from __future__ import annotations

import tempfile
import io
import os
import signal
import subprocess
import sys
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


def _lease_holder(tmp_path: Path) -> subprocess.Popen[str]:
    root = Path(__file__).resolve().parents[3]
    package_paths = os.pathsep.join(str(root / "packages" / name) for name in (
        "creator-domain", "creator-service", "creator-provider",
    ))
    process = subprocess.Popen(
        [sys.executable, "-c", """
import time
from creator_service.temp_byte_lease import temp_byte_lease
with temp_byte_lease(1, 1):
    print("acquired", flush=True)
    time.sleep(30)
"""],
        stdout=subprocess.PIPE, text=True,
        env={**os.environ, "PYTHONPATH": package_paths, "TMPDIR": str(tmp_path)},
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "acquired"
    return process


def test_dead_process_byte_lease_is_reclaimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a subprocess is killed while holding a staging byte lease.
    process = _lease_holder(tmp_path)
    process.send_signal(signal.SIGKILL)
    process.wait(timeout=5)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    disk_usage = type("DiskUsage", (), {"free": 100})()
    monkeypatch.setattr("creator_service.temp_byte_lease.shutil.disk_usage", lambda _: disk_usage)

    # When a successor requests all otherwise available capacity.
    with temp_byte_lease(80, 20):
        lease_count = len(list((tmp_path / ".media-byte-leases").glob("*.lease")))

    # Then the orphan is reclaimed and only the successor lease was present.
    assert lease_count == 1


def test_live_process_byte_lease_remains_reserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a live subprocess owns a staging byte lease.
    process = _lease_holder(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    disk_usage = type("DiskUsage", (), {"free": 100})()
    monkeypatch.setattr("creator_service.temp_byte_lease.shutil.disk_usage", lambda _: disk_usage)
    try:
        # When another worker requests capacity that overlaps the live lease.
        with pytest.raises(StorageLowWatermark), temp_byte_lease(80, 20):
            pass
    finally:
        process.terminate()
        process.wait(timeout=5)


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
