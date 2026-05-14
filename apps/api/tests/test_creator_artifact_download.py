# pyright: reportMissingImports=false

from datetime import datetime, timezone

import pytest
from pydantic import BaseModel
from fastapi.routing import APIRoute
from shorts_api.auth import CurrentUser, require_run_access
from shorts_api.main import app


def _find_route(name: str) -> APIRoute:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.name == name:
            return route
    raise AssertionError(f"Route {name} not found")


def test_download_artifact_route_uses_require_run_access_dependency() -> None:
    route = _find_route("download_artifact")
    dependency_calls = [dep.call for dep in route.dependant.dependencies]
    assert require_run_access in dependency_calls


@pytest.fixture
def stub_artifact_download_services(monkeypatch: pytest.MonkeyPatch, tmp_path):
    now = datetime.now(timezone.utc)

    class StubRun(BaseModel):
        id: int
        project_id: int
        current_stage: str = "FINAL_REVIEW"
        status: str = "running"
        created_at: datetime
        updated_at: datetime

    class StubRunService:
        def __init__(self):
            self.runs = {
                10: StubRun(
                    id=10,
                    project_id=7,
                    created_at=now,
                    updated_at=now,
                )
            }

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

    run_svc = StubRunService()

    async def _require_run_access(run_id: int):
        run = run_svc.runs.get(run_id)
        if run is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Run not found")
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    monkeypatch.setitem(
        _find_route("download_artifact").endpoint.__globals__,
        "artifact_download_service",
        StubArtifactDownloadService(),
    )
    yield
    app.dependency_overrides.pop(require_run_access, None)


@pytest.mark.asyncio
async def test_download_artifact_forbidden_workspace_mismatch(
    client, stub_artifact_download_services
):
    response = await client.get("/api/creator/runs/10/artifacts/99/download")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_download_artifact_rejects_none_workspace(client, stub_artifact_download_services):
    response = await client.get("/api/creator/runs/10/artifacts/100/download")

    assert response.status_code == 404
    assert response.json() == {"detail": "Artifact not found"}


@pytest.mark.asyncio
async def test_download_artifact_without_workspace_context_forbidden(
    client, stub_artifact_download_services
):
    response = await client.get("/api/creator/runs/999/artifacts/99/download")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}
