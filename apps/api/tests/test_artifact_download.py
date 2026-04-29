from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from shorts_api.main import app


class StubArtifactDownloadService:
    def __init__(self, artifact: dict[str, object] | None) -> None:
        self.artifact = artifact

    async def get_artifact_by_id(self, artifact_id: int) -> dict[str, object] | None:
        if self.artifact is None:
            return None
        if self.artifact.get("id") != artifact_id:
            return None
        return dict(self.artifact)


class StubRunStorage:
    async def get_run(self, run_id: int) -> dict[str, int]:
        return {"id": run_id, "project_id": 1}


class StubRunService:
    def __init__(self) -> None:
        self.storage = StubRunStorage()


class StubProject:
    def __init__(self) -> None:
        self.workspace_id = 1


class StubProjectService:
    async def get_project(self, project_id: int) -> StubProject | None:
        if project_id != 1:
            return None
        return StubProject()


def _iter_api_routes() -> list[APIRoute]:
    return [route for route in app.routes if isinstance(route, APIRoute)]


def _patch_route_services(
    monkeypatch: pytest.MonkeyPatch, artifact_service: StubArtifactDownloadService
) -> None:
    for route in _iter_api_routes():
        if route.name == "download_artifact":
            monkeypatch.setitem(
                route.endpoint.__globals__, "artifact_download_service", artifact_service
            )
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", StubRunService())
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", StubProjectService())


@pytest.mark.asyncio
async def test_download_artifact_returns_file(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    artifact_rel_path = "1/100/audio.wav"
    target_path = tmp_path / artifact_rel_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(b"test-audio")

    stub = StubArtifactDownloadService(
        {
            "id": 900,
            "run_id": 100,
            "file_path": artifact_rel_path,
            "storage_provider": "local",
            "content_type": "audio/wav",
        }
    )

    _patch_route_services(monkeypatch, stub)

    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    response = await client.get("/api/creator/runs/100/artifacts/900/download")

    assert response.status_code == 200
    assert response.content == b"test-audio"


@pytest.mark.asyncio
async def test_download_artifact_mismatched_run_id_returns_404(
    client,
    monkeypatch: pytest.MonkeyPatch,
):
    stub = StubArtifactDownloadService(
        {
            "id": 901,
            "run_id": 999,
            "file_path": "1/999/audio.wav",
            "storage_provider": "local",
        }
    )

    _patch_route_services(monkeypatch, stub)

    response = await client.get("/api/creator/runs/100/artifacts/901/download")

    assert response.status_code == 404
    assert response.json() == {"detail": "Artifact not found"}


@pytest.mark.asyncio
async def test_download_artifact_nonexistent_returns_404(client, monkeypatch: pytest.MonkeyPatch):
    stub = StubArtifactDownloadService(None)
    _patch_route_services(monkeypatch, stub)

    response = await client.get("/api/creator/runs/100/artifacts/902/download")

    assert response.status_code == 404
    assert response.json() == {"detail": "Artifact not found"}


@pytest.mark.asyncio
async def test_old_artifact_endpoint_returns_404_for_missing_file(client):
    """Old endpoint now serves files directly; missing files return 404."""
    response = await client.get("/artifacts/1/100/audio.wav")

    assert response.status_code == 404
