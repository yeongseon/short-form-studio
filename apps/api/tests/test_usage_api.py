# pyright: reportMissingImports=false

from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from shorts_api.main import app


class StubUsageService:
    async def get_monthly_summary(self, workspace_id: int):
        from datetime import datetime, timezone

        return type(
            "Summary",
            (),
            {
                "model_dump": lambda self, mode="json": {
                    "total_llm_calls": 2,
                    "total_image_generations": 3,
                    "total_tts_seconds": 4.0,
                    "total_estimated_cost_usd": 1.23,
                    "by_provider": {"openai": 1.23},
                    "by_operation": {"llm": 2},
                    "period_start": datetime(2026, 4, 1, tzinfo=timezone.utc).isoformat(),
                    "period_end": datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
                    "workspace_id": workspace_id,
                }
            },
        )()

    async def list_run_events(self, run_id: int, workspace_id: int | None = None):
        from datetime import datetime, timezone

        row = {
            "id": 1,
            "workspace_id": workspace_id or 1,
            "project_id": 2,
            "run_id": run_id,
            "provider": "openai",
            "model_key": "gpt-4o-mini",
            "operation_type": "llm",
            "input_tokens": 10,
            "output_tokens": 5,
            "image_count": None,
            "audio_seconds": None,
            "estimated_cost_usd": 0.01,
            "created_at": datetime(2026, 4, 1, tzinfo=timezone.utc).isoformat(),
        }
        return [type("Event", (), {"model_dump": lambda self, mode="json": row})()]


def _stub_authenticated_context(_request) -> tuple[int, int]:
    return 10, 5


async def _allow_check_access(workspace_id: int, user_id: int) -> bool:
    return True


async def _deny_check_access(workspace_id: int, user_id: int) -> bool:
    return False


@pytest.fixture
def stub_usage_service(monkeypatch: pytest.MonkeyPatch) -> StubUsageService:
    stub = StubUsageService()
    fake_ws = SimpleNamespace(check_access=_allow_check_access)
    for route in app.routes:
        if isinstance(route, APIRoute) and route.name in {"get_workspace_usage", "get_run_usage"}:
            monkeypatch.setitem(route.endpoint.__globals__, "usage_service", stub)
            monkeypatch.setitem(route.endpoint.__globals__, "workspace_service", fake_ws)
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "_get_authenticated_context",
                _stub_authenticated_context,
            )
    return stub


@pytest.mark.asyncio
async def test_get_workspace_usage_returns_summary(client, stub_usage_service: StubUsageService):
    _ = stub_usage_service
    response = await client.get("/api/creator/usage/workspace/5")

    assert response.status_code == 200
    body = response.json()
    assert body["total_llm_calls"] == 2
    assert body["total_estimated_cost_usd"] == 1.23


@pytest.mark.asyncio
async def test_get_run_usage_returns_events(client, stub_usage_service: StubUsageService):
    _ = stub_usage_service
    response = await client.get("/api/creator/usage/run/42")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["run_id"] == 42
    assert body[0]["provider"] == "openai"


@pytest.mark.asyncio
async def test_workspace_usage_for_non_member_returns_404(client, monkeypatch: pytest.MonkeyPatch):
    fake_ws = SimpleNamespace(check_access=_deny_check_access)

    for route in app.routes:
        if isinstance(route, APIRoute) and route.name in {"get_workspace_usage", "get_run_usage"}:
            monkeypatch.setitem(route.endpoint.__globals__, "workspace_service", fake_ws)
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "_get_authenticated_context",
                _stub_authenticated_context,
            )

    response = await client.get("/api/creator/usage/workspace/5")

    assert response.status_code == 404
    assert response.json()["detail"] == "Not found"
