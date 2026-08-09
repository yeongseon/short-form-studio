# pyright: reportMissingImports=false

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.routing import APIRoute
from shorts_api.auth import CurrentUser, require_current_user, require_run_access
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

    async def get_run(self, run_id: int) -> dict[str, int] | None:
        return await self.storage.get_run(run_id)


class StubProject:
    def __init__(self) -> None:
        self.workspace_id = 1


class StubProjectService:
    async def get_project(
        self, project_id: int, workspace_id: int | None = None
    ) -> StubProject | None:
        if project_id != 1:
            return None
        return StubProject()


def _iter_api_routes() -> list[APIRoute]:
    return [route for route in app.routes if isinstance(route, APIRoute)]


async def _stub_check_access(workspace_id: int, user_id: int) -> bool:
    return workspace_id == 1 and user_id == 101


def _patch_route_services(
    monkeypatch: pytest.MonkeyPatch, artifact_service: StubArtifactDownloadService
) -> None:
    async def stub_require_current_user(request: Request):
        _ = request
        return SimpleNamespace(user_id=101, workspace_id=1)

    monkeypatch.setitem(app.dependency_overrides, require_current_user, stub_require_current_user)

    async def stub_require_run_access(run_id: int) -> tuple[CurrentUser, object]:
        run = await StubRunService().get_run(run_id)
        if run is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Run not found")
        return CurrentUser(user_id=101, workspace_id=1), SimpleNamespace(**run)

    monkeypatch.setitem(app.dependency_overrides, require_run_access, stub_require_run_access)

    for route in _iter_api_routes():
        if route.name == "download_artifact":
            monkeypatch.setitem(
                route.endpoint.__globals__, "artifact_download_service", artifact_service
            )
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", StubRunService())
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", StubProjectService())
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "workspace_service",
                SimpleNamespace(check_access=_stub_check_access),
            )


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
async def test_download_artifact_uses_storage_key_over_absolute_file_path(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Worker-format artifact must download successfully (#584).

    Workers store the absolute path in file_path and the root-relative
    storage_key separately. The route must prefer storage_key; using
    file_path directly triggers the leading-component guard and returns 404.
    """
    artifact_root = tmp_path
    rel_key = "1/render/output.mp4"
    target = artifact_root / rel_key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"worker-format-video")

    # Mirrors what render_video.py + PostgresRenderStorage persist:
    #   file_path = absolute ({ARTIFACT_ROOT}/...)
    #   storage_key = root-relative
    stub = StubArtifactDownloadService(
        {
            "id": 910,
            "run_id": 100,
            "file_path": str(artifact_root / rel_key),
            "storage_key": rel_key,
            "storage_provider": "local",
            "content_type": "video/mp4",
        }
    )

    _patch_route_services(monkeypatch, stub)
    monkeypatch.setenv("ARTIFACT_ROOT", str(artifact_root))

    response = await client.get("/api/creator/runs/100/artifacts/910/download")

    assert response.status_code == 200
    assert response.content == b"worker-format-video"


@pytest.mark.asyncio
async def test_download_artifact_normalizes_legacy_absolute_file_path(
    client, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Legacy rows without storage_key must still resolve via file_path (#584).

    Some rows may predate storage_key. The route should strip a leading
    ARTIFACT_ROOT prefix from file_path so those downloads keep working.
    """
    artifact_root = tmp_path
    rel_key = "1/legacy/audio.wav"
    target = artifact_root / rel_key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"legacy-audio")

    stub = StubArtifactDownloadService(
        {
            "id": 911,
            "run_id": 100,
            "file_path": str(artifact_root / rel_key),  # absolute, no storage_key
            "storage_provider": "local",
        }
    )

    _patch_route_services(monkeypatch, stub)
    monkeypatch.setenv("ARTIFACT_ROOT", str(artifact_root))

    response = await client.get("/api/creator/runs/100/artifacts/911/download")

    assert response.status_code == 200
    assert response.content == b"legacy-audio"

@pytest.mark.asyncio
async def test_old_artifact_endpoint_returns_404_for_missing_file(client):
    response = await client.get("/artifacts/1/100/audio.wav")
    assert response.status_code == 404
