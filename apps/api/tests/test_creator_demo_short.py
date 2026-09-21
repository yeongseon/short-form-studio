# pyright: reportMissingImports=false

"""SF-76: demo Short flow route tests (auth/404, disclosure, seed, no-bypass)."""

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from shorts_api.auth import CurrentUser, require_project_access
from shorts_api.main import app
from shorts_api.app_factory import create_app


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


@pytest.fixture
def demo_env(monkeypatch: pytest.MonkeyPatch):
    stub_service = _StubRunService()
    configured = {"providers": ["openai", "groq"]}

    for route in _demo_routes():
        monkeypatch.setitem(
            route.endpoint.__globals__,
            "list_configured_providers",
            lambda: list(configured["providers"]),
        )
        monkeypatch.setitem(route.endpoint.__globals__, "run_service", stub_service)

    async def _require_project_access(project_id: int) -> tuple[CurrentUser, _StubProject]:
        return CurrentUser(user_id=1, workspace_id=1), _StubProject(project_id)

    app.dependency_overrides[require_project_access] = _require_project_access
    yield stub_service, configured
    app.dependency_overrides.pop(require_project_access, None)


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
async def test_demo_seed_creates_idea_ready_run(client, demo_env):
    stub_service, _ = demo_env
    response = await client.post("/api/creator/projects/5/demo-short/runs")
    assert response.status_code == 201
    body = response.json()
    assert body["run"]["current_stage"] == "IDEA_READY"
    assert body["run"]["status"] == "pending"
    assert len(stub_service.create_calls) == 1
    assert stub_service.create_calls[0]["current_stage"] == "IDEA_READY"


@pytest.mark.asyncio
async def test_demo_seed_refuses_when_prerequisites_not_configured(client, demo_env):
    stub_service, configured = demo_env
    configured["providers"] = []  # no LLM provider -> not ready
    response = await client.post("/api/creator/projects/5/demo-short/runs")
    assert response.status_code == 409
    assert len(stub_service.create_calls) == 0
