import asyncio

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
