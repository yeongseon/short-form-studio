# pyright: reportMissingImports=false

"""SF-77: onboarding guidance route tests (auth/404, disclosure, first-run vs returning)."""

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from shorts_api.app_factory import create_app
from shorts_api.auth import CurrentUser, require_workspace_access
from shorts_api.main import app


class _StubProjectService:
    def __init__(self, count: int) -> None:
        self._count = count
        self.count_calls: list[int | None] = []

    async def count_projects(self, workspace_id: int | None = None) -> int:
        self.count_calls.append(workspace_id)
        return self._count


def _onboarding_routes() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute) and "onboarding" in r.path]


@pytest.fixture
def onboarding_env(monkeypatch: pytest.MonkeyPatch):
    state = {"providers": ["openai"], "project_count": 0}

    for route in _onboarding_routes():
        monkeypatch.setitem(
            route.endpoint.__globals__,
            "list_configured_providers",
            lambda: list(state["providers"]),
        )
        monkeypatch.setitem(
            route.endpoint.__globals__,
            "project_service",
            _StubProjectService(int(state["project_count"])),
        )

    async def _require_workspace_access(workspace_id: int) -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=workspace_id)

    app.dependency_overrides[require_workspace_access] = _require_workspace_access
    yield state
    app.dependency_overrides.pop(require_workspace_access, None)


@pytest.mark.asyncio
async def test_onboarding_requires_authentication():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/creator/workspaces/1/onboarding")
    assert response.status_code in {401, 403, 404}


@pytest.mark.asyncio
async def test_onboarding_first_run_discloses_path_presets_and_gates(client, onboarding_env):
    response = await client.get("/api/creator/workspaces/1/onboarding")
    assert response.status_code == 200
    body = response.json()
    assert body["is_first_run"] is True
    assert body["flow"] == "first_run"
    assert body["steps"] == [
        "idea",
        "duration",
        "style",
        "optional_assets",
        "draft",
        "preview",
        "download",
        "edit",
    ]
    assert body["duration_preset_ids"] == ["15", "30", "45", "60", "90"]
    assert body["review_gates"] == [
        "SCRIPT_REVIEW",
        "VISUAL_PLAN_REVIEW",
        "VISUAL_ASSET_REVIEW",
        "FINAL_REVIEW",
    ]
    assert body["custom_duration_hint_seconds"] == 180


@pytest.mark.asyncio
async def test_onboarding_returning_when_workspace_has_projects(client, onboarding_env):
    onboarding_env["project_count"] = 3
    # Rebind the stubbed service with the new count.
    for route in _onboarding_routes():
        route.endpoint.__globals__["project_service"] = _StubProjectService(3)
    response = await client.get("/api/creator/workspaces/1/onboarding")
    assert response.status_code == 200
    body = response.json()
    assert body["is_first_run"] is False
    assert body["flow"] == "returning"


@pytest.mark.asyncio
async def test_onboarding_no_core_duration_ceiling_in_response(client, onboarding_env):
    response = await client.get("/api/creator/workspaces/1/onboarding")
    body = response.json()
    assert "max_duration_seconds" not in body
    assert "duration_ceiling_seconds" not in body


@pytest.mark.asyncio
async def test_onboarding_scopes_project_count_to_path_workspace(client, monkeypatch):
    # First-run/returning must be decided from the PATH workspace, not the
    # authenticated user's default workspace.
    stub = _StubProjectService(0)
    for route in _onboarding_routes():
        monkeypatch.setitem(
            route.endpoint.__globals__,
            "list_configured_providers",
            lambda: ["openai"],
        )
        monkeypatch.setitem(route.endpoint.__globals__, "project_service", stub)

    async def _require_workspace_access(workspace_id: int) -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=999)

    app.dependency_overrides[require_workspace_access] = _require_workspace_access
    try:
        response = await client.get("/api/creator/workspaces/42/onboarding")
    finally:
        app.dependency_overrides.pop(require_workspace_access, None)

    assert response.status_code == 200
    assert stub.count_calls == [42]
