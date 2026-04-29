import pytest

from shorts_api.routes import creator_artifact_download as route_mod


class _StubRunStorage:
    async def get_run(self, run_id: int):
        return {"id": run_id, "project_id": 1}


class _StubRunService:
    def __init__(self):
        self.storage = _StubRunStorage()


class _StubProject:
    workspace_id = 1


class _StubProjectService:
    async def get_project(self, project_id: int):
        if project_id != 1:
            return None
        return _StubProject()


class _StubArtifactDownloadService:
    def __init__(self, row):
        self._row = row

    async def get_artifact_by_id(self, artifact_id: int):
        if self._row and self._row.get("id") == artifact_id:
            return self._row
        return None


class _StubStorageBackend:
    def download_url(self, key: str) -> str:
        return f"https://cdn.example.test/{key}"


@pytest.mark.asyncio
async def test_download_nonlocal_storage_redirects(client, monkeypatch: pytest.MonkeyPatch):
    artifact = {
        "id": 44,
        "run_id": 9,
        "file_path": "renders/output.mp4",
        "storage_provider": "s3",
        "storage_key": "tenant/renders/output.mp4",
    }

    monkeypatch.setattr(route_mod, "run_service", _StubRunService())
    monkeypatch.setattr(route_mod, "project_service", _StubProjectService())
    monkeypatch.setattr(
        route_mod, "artifact_download_service", _StubArtifactDownloadService(artifact)
    )

    from creator_service import object_storage

    monkeypatch.setattr(object_storage, "get_storage_backend", lambda: _StubStorageBackend())

    response = await client.get("/api/creator/runs/9/artifacts/44/download", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "https://cdn.example.test/tenant/renders/output.mp4"
