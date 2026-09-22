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

    async def list_projects(self, limit=20, offset=0, workspace_id=None):
        return []


class _StubHealth:
    async def check_model(self, host: str, *, endpoint: str | None = None):
        from creator_service.model_health_service import ModelHealthResult, ModelStatus

        return ModelHealthResult(model_name=host, endpoint=endpoint or host, status=ModelStatus.UNKNOWN)


class _StubTimeline:
    async def load_timeline(self, *, project_id: int, workspace_id: int):
        return None


def _onboarding_routes() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute) and "onboarding" in r.path]


def _stub_readiness_globals(monkeypatch, providers: list[str], project_stub) -> None:
    """Stub the P0-2 registry-SSOT readiness deps so a configured remote key
    satisfies its category without any real health probe or DB timeline."""
    from creator_service.model_health_service import ModelHealthResult, ModelStatus

    class _ConfiguredHealth:
        def __init__(self, remote_hosts: set[str]) -> None:
            self._remote = remote_hosts

        async def check_model(self, host: str, *, endpoint: str | None = None):
            status = ModelStatus.CONFIGURED if host in self._remote else ModelStatus.UNKNOWN
            return ModelHealthResult(model_name=host, endpoint=endpoint or host, status=status)

    # Map configured provider names to the hostnames the resolver probes.
    _HOSTS = {"openai": "api.openai.com", "groq": "api.groq.com"}
    remote_hosts = {_HOSTS[p] for p in providers if p in _HOSTS}
    for route in _onboarding_routes():
        g = route.endpoint.__globals__
        monkeypatch.setitem(g, "list_configured_providers", lambda: list(providers))
        monkeypatch.setitem(g, "project_service", project_stub)
        monkeypatch.setitem(g, "_health_service", _ConfiguredHealth(remote_hosts))
        monkeypatch.setitem(g, "timeline_service", _StubTimeline())


@pytest.fixture
def onboarding_env(monkeypatch: pytest.MonkeyPatch):
    state = {"providers": ["openai"], "project_count": 0}
    _stub_readiness_globals(
        monkeypatch,
        list(state["providers"]),
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
        "TIMELINE_REVIEW",
        "FINAL_REVIEW",
    ]
    assert body["custom_duration_hint_seconds"] == 180


@pytest.mark.asyncio
async def test_onboarding_returning_when_workspace_has_projects(client, monkeypatch):
    # A workspace with existing projects is a returning user (first-run derives
    # from count_projects > 0, independent of first-draft detection).
    _stub_readiness_globals(monkeypatch, ["openai"], _StubProjectService(3))

    async def _require_workspace_access(workspace_id: int) -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=workspace_id)

    app.dependency_overrides[require_workspace_access] = _require_workspace_access
    try:
        response = await client.get("/api/creator/workspaces/1/onboarding")
    finally:
        app.dependency_overrides.pop(require_workspace_access, None)
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
    _stub_readiness_globals(monkeypatch, ["openai"], stub)

    async def _require_workspace_access(workspace_id: int) -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=999)

    app.dependency_overrides[require_workspace_access] = _require_workspace_access
    try:
        response = await client.get("/api/creator/workspaces/42/onboarding")
    finally:
        app.dependency_overrides.pop(require_workspace_access, None)

    assert response.status_code == 200
    # Every project-count read is scoped to the PATH workspace (42), never 999.
    assert set(stub.count_calls) == {42}
