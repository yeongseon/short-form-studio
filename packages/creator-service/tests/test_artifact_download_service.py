import asyncio
from pathlib import Path

import pytest
from creator_service.artifact_download_service import (
    ArtifactDownloadService,
    InMemoryArtifactDownloadStorage,
)


def run(coro):
    return asyncio.run(coro)


def test_get_artifact_by_id_returns_artifact() -> None:
    storage = InMemoryArtifactDownloadStorage()
    service = ArtifactDownloadService(storage)

    created = run(
        storage.save_artifact(
            {
                "run_id": 77,
                "file_path": "77/output.mp4",
                "artifact_type": "video",
                "storage_provider": "local",
            }
        )
    )

    fetched = run(service.get_artifact_by_id(created["id"]))
    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["run_id"] == 77
    assert fetched["file_path"] == "77/output.mp4"


def test_get_artifact_by_id_returns_none_for_missing() -> None:
    service = ArtifactDownloadService(InMemoryArtifactDownloadStorage())

    fetched = run(service.get_artifact_by_id(99999))
    assert fetched is None


@pytest.mark.asyncio
async def test_delete_artifacts_for_run_deletes_storage_and_db_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deleted_keys: list[str] = []
    deleted_rows: list[int] = []

    class _Backend:
        def delete(self, key: str) -> bool:
            deleted_keys.append(key)
            return True

    async def _fetch_all(_query: str, run_id: int) -> list[dict[str, object]]:
        assert run_id == 77
        return [
            {"storage_key": "77/audio.mp3", "storage_provider": "local"},
            {"storage_key": "77/video.mp4", "storage_provider": "s3"},
        ]

    async def _execute(_query: str, run_id: int) -> str:
        deleted_rows.append(run_id)
        return "DELETE 2"

    monkeypatch.setattr("creator_service.artifact_download_service.fetch_all", _fetch_all)
    monkeypatch.setattr("creator_service.artifact_download_service.execute", _execute)
    monkeypatch.setattr(
        "creator_service.artifact_download_service.get_storage_backend", lambda: _Backend()
    )

    service = ArtifactDownloadService(InMemoryArtifactDownloadStorage())
    await service.delete_artifacts_for_run(77)

    assert deleted_keys == ["77/audio.mp3", "77/video.mp4"]
    assert deleted_rows == [77]


@pytest.mark.asyncio
async def test_delete_artifacts_for_run_local_backend_cleans_run_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "55"
    run_dir.mkdir(parents=True)
    (run_dir / "orphan.tmp").write_text("x")

    class _Backend:
        provider = "local"

        def delete(self, _key: str) -> bool:
            return True

    async def _fetch_all(_query: str, _run_id: int) -> list[dict[str, object]]:
        return []

    async def _execute(_query: str, _run_id: int) -> str:
        return "DELETE 0"

    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setattr("creator_service.artifact_download_service.fetch_all", _fetch_all)
    monkeypatch.setattr("creator_service.artifact_download_service.execute", _execute)
    monkeypatch.setattr(
        "creator_service.artifact_download_service.get_storage_backend", lambda: _Backend()
    )

    service = ArtifactDownloadService(InMemoryArtifactDownloadStorage())
    await service.delete_artifacts_for_run(55)

    assert not run_dir.exists()
