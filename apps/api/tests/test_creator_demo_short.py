# pyright: reportMissingImports=false

"""SF-76 + P0-3: demo Short flow route tests (auth/404, disclosure, sample-backed seed)."""

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from shorts_api.auth import CurrentUser, require_project_access, require_workspace_access
from shorts_api.main import app
from shorts_api.app_factory import create_app


class _StubSeedResult:
    def __init__(self, run, project_id: int, timeline_id: str) -> None:
        self.run = run
        self.project_id = project_id
        self.timeline_id = timeline_id
        self.asset_id_map = {10: 501, 11: 501}


class _SeedSpy:
    """Records seed_demo_short calls and returns a real-id seed result."""

    def __init__(self, run_service) -> None:
        self.calls: list[dict] = []
        self._run_service = run_service

    async def __call__(self, *, workspace_id, project_service, media_asset_service, timeline_service, run_service):
        self.calls.append({"workspace_id": workspace_id})
        run = _StubRun(202, workspace_id)
        run_service.create_calls.append({"project_id": 202, "workspace_id": workspace_id, "current_stage": "IDEA_READY"})
        return _StubSeedResult(run, project_id=202, timeline_id="demo-timeline")


class _StubProject:
    def __init__(self, project_id: int, status: str = "active") -> None:
        self.id = project_id
        self.status = status


class _StubRun:
    def __init__(self, project_id: int, workspace_id: int) -> None:
        self.project_id = project_id
        self.workspace_id = workspace_id
        self.current_stage = "IDEA_READY"
        self.status = "pending"
        self.review_stage = None

    def model_dump(self, mode: str = "json") -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "current_stage": self.current_stage,
            "status": self.status,
            "review_stage": self.review_stage,
        }


class _StubRunService:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []

    async def create_run(self, **kwargs: object):  # noqa: ANN003
        self.create_calls.append(kwargs)
        return _StubRun(int(kwargs["project_id"]), int(kwargs["workspace_id"]))  # type: ignore[arg-type]


def _demo_routes() -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute) and "demo-short" in r.path]


class _ConfiguredHealth:
    """Health stub where the given remote hosts read CONFIGURED (key present,
    not probed) so a configured remote provider satisfies its category."""

    def __init__(self, providers: list[str]) -> None:
        hosts = {"openai": "api.openai.com", "groq": "api.groq.com"}
        self._remote = {hosts[p] for p in providers if p in hosts}

    async def check_model(self, host):
        from creator_service.model_health_service import ModelHealthResult, ModelStatus

        status = ModelStatus.CONFIGURED if host in self._remote else ModelStatus.UNKNOWN
        return ModelHealthResult(model_name=host, endpoint=host, status=status)


class _StubTimeline:
    async def load_timeline(self, *, project_id: int, workspace_id: int):
        return None


@pytest.fixture
def demo_env(monkeypatch: pytest.MonkeyPatch):
    stub_service = _StubRunService()
    seed_spy = _SeedSpy(stub_service)
    configured = {"providers": ["openai", "groq"]}

    def _apply(providers: list[str]) -> None:
        for route in _demo_routes():
            g = route.endpoint.__globals__
            monkeypatch.setitem(g, "list_configured_providers", lambda: list(providers))
            monkeypatch.setitem(g, "run_service", stub_service)
            monkeypatch.setitem(g, "_health_service", _ConfiguredHealth(providers))
            monkeypatch.setitem(g, "timeline_service", _StubTimeline())
            monkeypatch.setitem(g, "seed_demo_short", seed_spy)

    _apply(list(configured["providers"]))
    configured["_apply"] = _apply  # type: ignore[assignment]
    configured["_seed_spy"] = seed_spy  # type: ignore[assignment]

    async def _require_project_access(project_id: int) -> tuple[CurrentUser, _StubProject]:
        return CurrentUser(user_id=1, workspace_id=1), _StubProject(project_id)

    async def _require_workspace_access(workspace_id: int) -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=workspace_id)

    app.dependency_overrides[require_project_access] = _require_project_access
    app.dependency_overrides[require_workspace_access] = _require_workspace_access
    yield stub_service, configured
    app.dependency_overrides.pop(require_project_access, None)
    app.dependency_overrides.pop(require_workspace_access, None)


@pytest.mark.asyncio
async def test_demo_plan_requires_authentication():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/creator/projects/1/demo-short/plan")
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_demo_plan_discloses_costs_approvals_and_no_exposure(client, demo_env):
    response = await client.get("/api/creator/projects/1/demo-short/plan")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["required_approvals"] == [
        "SCRIPT_REVIEW",
        "VISUAL_PLAN_REVIEW",
        "VISUAL_ASSET_REVIEW",
        "FINAL_REVIEW",
    ]
    assert len(body["cost_line_items"]) == 3
    assert body["external_exposure"] == "none"
    import json as _json

    blob = _json.dumps(body)
    for leak in ("http://", "https://", "localtunnel", "ngrok", "serveo", "sk-"):
        assert leak not in blob


@pytest.mark.asyncio
async def test_demo_seed_creates_sample_backed_run_against_a_real_project(client, demo_env):
    stub_service, configured = demo_env
    response = await client.post("/api/creator/workspaces/7/demo-short/runs")
    assert response.status_code == 201
    body = response.json()
    # The run is created against a REAL seeded project (not a synthetic id=1).
    assert body["seeded_project_id"] == 202
    assert body["timeline_id"] == "demo-timeline"
    assert body["run"]["current_stage"] == "IDEA_READY"
    assert body["run"]["project_id"] == body["seeded_project_id"]
    # seed_demo_short was invoked for the path workspace.
    assert configured["_seed_spy"].calls == [{"workspace_id": 7}]


@pytest.mark.asyncio
async def test_demo_seed_requires_authentication():
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/creator/workspaces/1/demo-short/runs")
    assert response.status_code in {401, 403, 404}


@pytest.mark.asyncio
async def test_demo_seed_refuses_when_prerequisites_not_configured(client, demo_env):
    stub_service, configured = demo_env
    # No configured providers -> no LLM satisfied -> not ready -> refuse to seed.
    configured["_apply"]([])
    response = await client.post("/api/creator/workspaces/7/demo-short/runs")
    assert response.status_code == 409
    assert configured["_seed_spy"].calls == []
    assert len(stub_service.create_calls) == 0
