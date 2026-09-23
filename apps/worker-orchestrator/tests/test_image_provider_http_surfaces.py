import json
from functools import partial
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import celery_app
import httpx
import pytest
from creator_provider.exceptions import ProviderAuthError, RateLimitError
from creator_provider.image.groq_svg_provider import GroqSvgImageProvider
from creator_provider.image.huggingface_provider import HuggingFaceImageProvider
from creator_service.project_service import ProjectService
from creator_service.workspace_service import WorkspaceService
from fastapi import FastAPI, HTTPException, Request
from shorts_api import auth
from shorts_api.routes import creator_run_tasks
from worker_loop import run_in_worker_loop

from .provider_boundary_support import GenerationCase, generation_case as generation_case
from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import runner_case as runner_case


@pytest.mark.parametrize("generation_case", [
    ("generate_scene_image", "VISUAL_ASSET_GENERATING", (None, "groq-svg")),
    ("generate_scene_image", "VISUAL_ASSET_GENERATING", (None, "hf-flux-schnell")),
], indirect=True, ids=["groq", "hf"])
@pytest.mark.parametrize("status", [401, 403, 429])
def test_http_failure_reaches_persisted_task_api_and_dlq(
    generation_case: GenerationCase, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path, status: int, caplog: pytest.LogCaptureFixture,
) -> None:
    # Given the actual HTTP adapter, scene task, common runner, and memory/migrated PG stores.
    case = generation_case
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-private-key")
    monkeypatch.setenv("HF_TOKEN", "synthetic-private-key")
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    provider = (GroqSvgImageProvider("offline", "groq-svg") if case.args[-1] == "groq-svg"
                else HuggingFaceImageProvider("offline", "hf-flux-schnell"))
    registry = case.module.get_default_registry()
    registry.get_provider.return_value = provider
    handler = Mock(return_value=httpx.Response(status, text="synthetic-private-body",
                                              headers={"Retry-After": "73"}))
    async_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", partial(async_client, transport=httpx.MockTransport(handler)))
    sleep = AsyncMock()
    monkeypatch.setattr("asyncio.sleep", sleep)
    fallback = tmp_path / "failures.jsonl"
    monkeypatch.setattr(celery_app, "redis", None)
    monkeypatch.setattr(celery_app, "dlq_fallback_path", str(fallback))
    retry = Mock(wraps=case.task.retry)
    monkeypatch.setattr(case.task, "retry", retry)
    # When the real Celery trace reaches a terminal response (429 exhausts the Celery budget).
    result = case.task.apply(args=case.args, task_id="image-http-failure", throw=False,
                             retries=case.task.max_retries if status == 429 else 0)
    # Then one HTTP request reaches actionable, redacted persistence and authenticated API surfaces.
    assert result.state == "FAILURE"
    assert handler.call_count == 1
    sleep.assert_not_awaited()
    error_type = RateLimitError if status == 429 else ProviderAuthError
    category = "QUOTA" if status == 429 else "PROVIDER_AUTH"
    assert type(result.result) is error_type
    if status == 429:
        assert result.result.retry_after == "73"
        retry.assert_called_once()
        assert 0 <= retry.call_args.kwargs["countdown"] <= 600
    else:
        retry.assert_not_called()
    persisted = fallback.read_text()
    assert len(persisted.splitlines()) == 1
    failure = json.loads(persisted)["failure"]
    assert failure["category"] == category
    assert failure["retryable"] is (status == 429)
    for secret in ("synthetic-private-key", "synthetic-private-body"):
        assert secret not in persisted
        assert secret not in caplog.text

    projects, workspaces = ProjectService(), WorkspaceService()
    run_in_worker_loop(workspaces.create_workspace("Owner", "owner", 1))
    run_in_worker_loop(projects.create_project("Offline", "idea", idea_brief="Test", workspace_id=1))
    monkeypatch.setattr("creator_service.run_service.run_service", case.runner.runs)
    monkeypatch.setattr("creator_service.project_service.project_service", projects)
    monkeypatch.setattr(auth, "workspace_service", workspaces)
    monkeypatch.setattr(creator_run_tasks, "task_tracking_service", case.runner.tracking)
    app = FastAPI()
    app.include_router(creator_run_tasks.router, prefix="/api/creator")

    async def identity(request: Request) -> auth.CurrentUser:
        key = request.headers.get("X-API-Key")
        if key not in ("owner", "other"):
            raise HTTPException(401, "API key required")
        return auth.CurrentUser(user_id=1 if key == "owner" else 2, workspace_id=1 if key == "owner" else 2)

    app.dependency_overrides[auth.require_current_user] = identity

    async def verify_http() -> None:
        async with async_client(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/creator/runs/{case.runner.run_id}/tasks"
            response = await client.get(path, headers={"X-API-Key": "owner"})
            assert response.status_code == 200
            task = response.json()[0]
            assert (task["status"], task["error_code"]) == ("failed", category)
            assert task["failure"] == failure
            assert "synthetic-private" not in response.text
            if status in (401, 403):
                assert any("API key" in step for step in task["failure"]["recovery_steps"])
            foreign = await client.get(path, headers={"X-API-Key": "other"})
            absent = await client.get("/api/creator/runs/999999/tasks", headers={"X-API-Key": "owner"})
            assert foreign.status_code == absent.status_code == 404
            assert foreign.json() == absent.json() == {"detail": "Not found"}
            assert (await client.get(path)).status_code == 401

    run_in_worker_loop(verify_http())
