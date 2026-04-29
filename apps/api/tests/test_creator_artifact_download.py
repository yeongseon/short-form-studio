# pyright: reportMissingImports=false

from datetime import datetime, timezone

import pytest
from fastapi.routing import APIRoute
from shorts_api.auth import CurrentUser
from shorts_api.main import app


def _find_route(name: str) -> APIRoute:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.name == name:
            return route
    raise AssertionError(f"Route {name} not found")


@pytest.fixture
def stub_artifact_download_services(monkeypatch: pytest.MonkeyPatch, tmp_path):
    now = datetime.now(timezone.utc)

    class StubProject:
        def __init__(self, workspace_id: int | None):
            self.id = 7
            self.workspace_id = workspace_id
            self.created_at = now
            self.updated_at = now

    class StubRunStorage:
        async def get_run(self, run_id: int):
            if run_id != 10:
                return None
            return {"id": 10, "project_id": 7}

    class StubRunService:
        def __init__(self):
            self.storage = StubRunStorage()

    class StubProjectService:
        def __init__(self):
            self.workspace_id = 1

        async def get_project(self, project_id: int):
            if project_id != 7:
                return None
            return StubProject(workspace_id=self.workspace_id)

    class StubArtifactDownloadService:
        async def get_artifact_by_id(self, artifact_id: int):
            if artifact_id != 99:
                return None
            return {
                "id": 99,
                "run_id": 10,
                "file_path": "ok.txt",
                "storage_provider": "local",
                "content_type": "text/plain",
            }

    artifact_file = tmp_path / "ok.txt"
    artifact_file.write_text("ok", encoding="utf-8")
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("ARTIFACT_ACCESS_STRICT", "true")
    monkeypatch.setenv("API_KEY", "test-api-key")

    route = _find_route("download_artifact")
    stub_project_service = StubProjectService()
    auth_context = {"workspace_id": 1}

    async def stub_get_current_user(_request):
        return CurrentUser(user_id=123, workspace_id=auth_context["workspace_id"])

    monkeypatch.setitem(route.endpoint.__globals__, "run_service", StubRunService())
    monkeypatch.setitem(route.endpoint.__globals__, "project_service", stub_project_service)
    monkeypatch.setitem(
        route.endpoint.__globals__, "artifact_download_service", StubArtifactDownloadService()
    )
    monkeypatch.setitem(route.endpoint.__globals__, "get_current_user", stub_get_current_user)

    return {"project_service": stub_project_service, "auth_context": auth_context}


@pytest.mark.asyncio
async def test_download_artifact_forbidden_workspace_mismatch(
    client, stub_artifact_download_services
):
    stub_artifact_download_services["project_service"].workspace_id = 2
    response = await client.get("/api/creator/runs/10/artifacts/99/download")

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.asyncio
async def test_download_artifact_rejects_none_workspace(client, stub_artifact_download_services):
    stub_artifact_download_services["auth_context"]["workspace_id"] = None
    response = await client.get("/api/creator/runs/10/artifacts/99/download")

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


@pytest.mark.asyncio
async def test_download_artifact_without_workspace_context_forbidden(
    client, stub_artifact_download_services
):
    stub_artifact_download_services["auth_context"]["workspace_id"] = None
    response = await client.get("/api/creator/runs/10/artifacts/99/download")

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}
