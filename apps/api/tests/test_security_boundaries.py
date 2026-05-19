# pyright: reportMissingImports=false

"""Security boundary tests for auth, workspace isolation, and access control.

Covers:
1. /api/creator/* without API key returns 401
2. /healthz remains public
3. OPTIONS preflight remains allowed
4. create_project persists workspace_id
5. User A cannot GET user B's project (workspace isolation)
6. User A cannot GET user B's run
7. User A cannot mutate user B's run (generate/render/stop/delete)
8. artifact_id download denies cross-workspace access
9. Path artifact endpoints return 404 in production/staging
10. Default-deny does not block non-creator paths
"""

from __future__ import annotations

from typing import Any, Literal
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from shorts_api.auth import (
    ApiKeyMiddleware,
    CurrentUser,
    get_current_user,
    require_current_user,
)
from shorts_api.main import app


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubProject(BaseModel):
    id: int
    title: str
    source_type: Literal["idea", "markdown", "url", "pasted_json"] = "idea"
    idea_brief: str | None = None
    markdown_source: str | None = None
    url_source: str | None = None
    json_script: str | None = None
    status: str = "draft"
    created_at: datetime = datetime.now(timezone.utc)
    updated_at: datetime = datetime.now(timezone.utc)
    latest_run: dict[str, int | str | None] | None = None
    workspace_id: int | None = None


class StubRun(BaseModel):
    id: int
    project_id: int
    current_stage: str = "IDEA_READY"
    status: str = "active"
    active_task_id: str | None = None
    workspace_id: int | None = None
    model_config = {"extra": "allow"}

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "current_stage": self.current_stage,
            "status": self.status,
            "active_task_id": self.active_task_id,
            "workspace_id": self.workspace_id,
        }


# User is in workspace 1; workspace 2 belongs to someone else
_WS2_PROJECT = StubProject(id=99, title="Other", workspace_id=2, idea_brief="theirs")
_WS2_RUN = StubRun(id=99, project_id=99, workspace_id=2)


# ---------------------------------------------------------------------------
# Minimal auth app for default-deny tests (no DB needed)
# ---------------------------------------------------------------------------


def _make_auth_app() -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    test_app.add_middleware(ApiKeyMiddleware)

    @test_app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @test_app.get("/api/creator/projects")
    async def list_projects():
        return {"projects": []}

    @test_app.get("/api/other/data")
    async def other_data():
        return {"data": "open"}

    return test_app


@pytest.fixture
async def auth_client():
    test_app = _make_auth_app()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests 1-3, 10: Auth middleware default-deny
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creator_endpoint_without_api_key_returns_401(auth_client: AsyncClient):
    response = await auth_client.get("/api/creator/projects")
    assert response.status_code == 401
    assert response.json()["detail"] == "API key required"


@pytest.mark.asyncio
async def test_healthz_is_public(auth_client: AsyncClient):
    response = await auth_client.get("/healthz")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_options_preflight_allowed_without_api_key(auth_client: AsyncClient):
    response = await auth_client.options(
        "/api/creator/projects",
        headers={"Origin": "http://localhost:5174", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_non_creator_paths_not_blocked(auth_client: AsyncClient):
    response = await auth_client.get("/api/other/data")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Test 4: create_project passes workspace_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_project_passes_workspace_id(client, monkeypatch: pytest.MonkeyPatch):
    from shorts_api.main import projects_router

    captured: list[dict[str, Any]] = []

    class CapturingProjectService:
        create_project_calls = captured

        async def create_project(self, **kwargs: Any) -> StubProject:
            captured.append(kwargs)
            return StubProject(id=99, **kwargs)

    svc = CapturingProjectService()
    for route in projects_router.routes:
        if isinstance(route, APIRoute) and route.name == "create_project":
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", svc)

    response = await client.post(
        "/api/creator/projects",
        json={"title": "Test", "source_type": "idea", "idea_brief": "test"},
    )
    assert response.status_code == 201
    assert len(captured) == 1
    assert captured[0]["workspace_id"] == 1


# ---------------------------------------------------------------------------
# Tests 5-7: Workspace isolation (cross-workspace denial)
# ---------------------------------------------------------------------------


def _patch_for_cross_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch services so require_run_access / require_project_access find workspace-2 objects."""

    class CrossWsProjectService:
        async def get_project(
            self, project_id: int, workspace_id: int | None = None
        ) -> StubProject | None:
            if project_id == 99:
                return _WS2_PROJECT
            return None

    class CrossWsRunService:
        async def get_run(self, run_id: int, workspace_id: int | None = None) -> StubRun | None:
            if run_id == 99:
                return _WS2_RUN
            return None

    monkeypatch.setattr("creator_service.project_service.project_service", CrossWsProjectService())
    monkeypatch.setattr("creator_service.run_service.run_service", CrossWsRunService())


@pytest.mark.asyncio
async def test_cannot_access_other_workspace_project(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    _patch_for_cross_workspace(monkeypatch)

    response = await client.get("/api/creator/projects/99")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_access_other_workspace_run(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    _patch_for_cross_workspace(monkeypatch)

    response = await client.get("/api/creator/runs/99")
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/creator/runs/99/restart"),
        ("post", "/api/creator/runs/99/stop"),
        ("post", "/api/creator/runs/99/resume"),
        ("post", "/api/creator/runs/99/approve-script"),
        ("post", "/api/creator/runs/99/generate-script"),
        ("delete", "/api/creator/runs/99"),
    ],
)
async def test_cannot_mutate_other_workspace_run(
    method: str,
    path: str,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_for_cross_workspace(monkeypatch)

    client_method = getattr(client, method)
    if method == "post":
        response = await client_method(path, json={})
    else:
        response = await client_method(path)

    assert response.status_code == 404, f"{method.upper()} {path} returned {response.status_code}"


# ---------------------------------------------------------------------------
# Test 8: Artifact download cross-workspace denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_artifact_download_denies_cross_workspace(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    _patch_for_cross_workspace(monkeypatch)

    from shorts_api.routes import creator_artifact_download

    class _StorageStub:
        async def get_run(
            self, run_id: int, workspace_id: int | None = None
        ) -> dict[str, object] | None:
            if run_id == 99:
                return {"id": 99, "project_id": 99, "workspace_id": 2}
            return None

    class CrossWsRunSvc:
        storage = _StorageStub()

    class CrossWsProjSvc:
        async def get_project(
            self, project_id: int, workspace_id: int | None = None
        ) -> StubProject | None:
            if project_id == 99:
                return _WS2_PROJECT
            return None

    for route in app.routes:
        if isinstance(route, APIRoute) and route.name == "download_artifact":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", CrossWsRunSvc())
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", CrossWsProjSvc())

    response = await client.get("/api/creator/runs/99/artifacts/1/download")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test 9: Path artifact endpoints blocked in production/staging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("env", ["production", "staging"])
async def test_path_artifact_endpoints_blocked_in_prod(
    env: str, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ENVIRONMENT", env)

    response = await client.get("/artifacts/some/path")
    assert response.status_code == 404

    response = await client.get("/api/artifacts/files/some/path")
    assert response.status_code == 404
