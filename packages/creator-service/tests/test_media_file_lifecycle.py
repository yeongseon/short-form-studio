import io
import tempfile
from pathlib import Path
from threading import Event, get_ident
from typing import BinaryIO

import anyio
import pytest
from PIL import Image

from creator_service.media_asset_service import InMemoryMediaAssetStorage, MediaAssetService
from creator_service.media_file_ingestion import FileUpload
from creator_service.media_upload_validation import MediaUploadRejected
from creator_service.object_storage import LocalStorageBackend, StorageResult


def png() -> bytes:
    with io.BytesIO() as buffer:
        Image.new("RGB", (8, 12)).save(buffer, format="PNG")
        return buffer.getvalue()


@pytest.fixture
def staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "staging"
    directory.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(directory))
    return directory


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,mime,data,limit", [
    ("../escape.png", "image/png", png(), 1000),
    ("a\\b.png", "image/png", png(), 1000),
    ("a\x00.png", "image/png", png(), 1000),
    ("image.png", "image/png", b"fake", 1000),
    ("image.png", "text/plain", png(), 1000),
    ("image.png", "image/png", b"", 1000),
    ("image.png", "image/png", png(), 10),
])
async def test_rejection_cleans_only_staging(
    staging: Path, tmp_path: Path, filename: str, mime: str, data: bytes, limit: int,
) -> None:
    # Given invalid input alongside an existing accepted artifact.
    root = tmp_path / "objects"
    backend = LocalStorageBackend(str(root))
    backend.upload("existing.png", png())
    service = MediaAssetService(backend, InMemoryMediaAssetStorage())
    with io.BytesIO(data) as source:
        # When validation rejects the upload.
        with pytest.raises(MediaUploadRejected):
            await service.create_file_asset(source, FileUpload(7, filename, mime, "image", limit))
        # Then the borrowed source remains open; only owned staging is removed.
        assert not source.closed
    assert list(staging.iterdir()) == []
    assert list(root.iterdir()) == [root / "existing.png"]
    assert (await service.list_assets(workspace_id=7)).total == 0


class FailingMetadata(InMemoryMediaAssetStorage):
    def __init__(self, commit: bool) -> None:
        super().__init__()
        self.commit = commit

    async def save_asset(self, row: dict[str, object]) -> dict[str, object]:
        if self.commit:
            await super().save_asset(row)
        raise ConnectionError("ambiguous acknowledgement")


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [False, True])
async def test_save_failure_retains_durable_object_and_cleans_staging(
    tmp_path: Path, staging: Path, commit: bool,
) -> None:
    # Given metadata failure that may occur after commit.
    root = tmp_path / "objects"
    service = MediaAssetService(LocalStorageBackend(str(root)), FailingMetadata(commit))
    with io.BytesIO(png()) as source:
        # When the save acknowledgement fails.
        with pytest.raises(ConnectionError):
            await service.create_file_asset(source, FileUpload(7, "image.png", "image/png", "image", 1000))
    # Then durable bytes are retained for both outcomes, never guessed safe to delete.
    assert len(list(root.rglob("*.png"))) == 1
    assert list(staging.iterdir()) == []
    assert (await service.list_assets(workspace_id=7)).total == int(commit)


@pytest.mark.asyncio
async def test_cancellation_during_copy_joins_thread_and_cleans_staging(
    tmp_path: Path, staging: Path,
) -> None:
    # Given a blocking read on the offload thread.
    entered = anyio.Event()
    release = Event()
    exited = Event()
    event_thread = get_ident()

    class PausedSource(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert get_ident() != event_thread
            anyio.from_thread.run_sync(entered.set)
            assert release.wait(5)
            exited.set()
            return super().read(size)

    service = MediaAssetService(LocalStorageBackend(str(tmp_path / "objects")), InMemoryMediaAssetStorage())
    with PausedSource(png()) as source:
        async with anyio.create_task_group() as group:
            group.start_soon(service.create_file_asset, source, FileUpload(7, "image.png", "image/png", "image", 1000))
            await entered.wait()
            # When cancellation occurs while the thread owns the file.
            group.cancel_scope.cancel()
            release.set()
        # Then the thread has exited before cleanup and no durable object exists.
        assert exited.is_set()
        assert not source.closed
    assert list(staging.iterdir()) == []
    assert not (tmp_path / "objects").exists()


@pytest.mark.asyncio
async def test_started_upload_and_metadata_finish_after_cancellation(
    tmp_path: Path, staging: Path,
) -> None:
    # Given a started storage write and a metadata operation that yields.
    entered = anyio.Event()
    release = Event()
    event_thread = get_ident()

    class PausedStorage(LocalStorageBackend):
        def upload(self, key: str, data: bytes | BinaryIO, content_type: str = "application/octet-stream") -> StorageResult:
            assert get_ident() != event_thread
            assert not isinstance(data, bytes)
            anyio.from_thread.run_sync(entered.set)
            assert release.wait(5)
            return super().upload(key, data, content_type)

    class YieldingMetadata(InMemoryMediaAssetStorage):
        async def save_asset(self, row: dict[str, object]) -> dict[str, object]:
            await anyio.lowlevel.checkpoint()
            return await super().save_asset(row)

    service = MediaAssetService(PausedStorage(str(tmp_path / "objects")), YieldingMetadata())
    with io.BytesIO(png()) as source:
        async with anyio.create_task_group() as group:
            group.start_soon(service.create_file_asset, source, FileUpload(7, "image.png", "image/png", "image", 1000))
            await entered.wait()
            # When the request is cancelled after storage started.
            group.cancel_scope.cancel()
            release.set()
    # Then metadata and object survive while request-owned staging is removed.
    assert (await service.list_assets(workspace_id=7)).total == 1
    assert len(list((tmp_path / "objects").rglob("*.png"))) == 1
    assert list(staging.iterdir()) == []


@pytest.mark.asyncio
async def test_storage_failure_cleans_staging(tmp_path: Path, staging: Path) -> None:
    # Given an unavailable object backend.
    class Unavailable(LocalStorageBackend):
        def upload(self, key: str, data: bytes | BinaryIO, content_type: str = "application/octet-stream") -> StorageResult:
            raise OSError("storage unavailable")

    service = MediaAssetService(Unavailable(str(tmp_path / "objects")), InMemoryMediaAssetStorage())
    with io.BytesIO(png()) as source:
        # When storage raises.
        with pytest.raises(OSError):
            await service.create_file_asset(source, FileUpload(7, "image.png", "image/png", "image", 1000))
    # Then owned staging is removed and metadata remains absent.
    assert list(staging.iterdir()) == []
    assert (await service.list_assets(workspace_id=7)).total == 0


@pytest.mark.asyncio
async def test_unrecognized_video_container_cannot_fall_back_to_declared_mime(
    tmp_path: Path, staging: Path,
) -> None:
    # Given a real playable AVI with a claimed MP4 MIME.
    import subprocess

    path = tmp_path / "video.avi"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=16x24:d=0.2", str(path)],
        check=True,
    )
    service = MediaAssetService(
        LocalStorageBackend(str(tmp_path / "objects")), InMemoryMediaAssetStorage(),
    )
    with path.open("rb") as source:
        # When the actual file is probed during streaming ingestion.
        with pytest.raises(MediaUploadRejected):
            await service.create_file_asset(
                source, FileUpload(7, "video.mp4", "video/mp4", "video", 100_000),
            )
    # Then unsupported actual containers create neither objects nor metadata.
    assert list(staging.iterdir()) == []
    assert not (tmp_path / "objects").exists()
    assert (await service.list_assets(workspace_id=7)).total == 0
