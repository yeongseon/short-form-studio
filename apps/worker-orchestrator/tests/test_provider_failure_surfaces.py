import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import celery_app
from creator_provider.exceptions import ProviderAuthError, ProviderError, ProviderTimeoutError, ProviderValidationError, RateLimitError
from creator_service.project_service import ProjectService
from creator_service.workspace_service import WorkspaceService
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from shorts_api import auth
from shorts_api.routes import creator_run_tasks
from worker_loop import run_in_worker_loop

from .provider_boundary_support import GenerationCase, generation_case as generation_case
from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import runner_case as runner_case


@pytest.mark.parametrize("error_type,category,retryable", [
    (ProviderAuthError, "PROVIDER_AUTH", False),
    (ProviderValidationError, "VALIDATION", False),
    (ProviderError, "UNAVAILABLE", True),
    (ProviderTimeoutError, "UNAVAILABLE", True),
    (RateLimitError, "QUOTA", True),
])
def test_real_task_failure_reaches_api_and_dlq(
    generation_case: GenerationCase, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    error_type: type[ProviderError], category: str, retryable: bool,
) -> None:
    # Given actual task execution and a real DLQ fallback file, with synthetic secrets only.
    case = generation_case
    error = error_type("invalid credential token=synthetic-private-value https://secret.invalid/private")
    case.provider.generate.side_effect = error
    case.provider.transcribe.side_effect = error
    fallback = tmp_path / "failures.jsonl"
    monkeypatch.setattr(celery_app, "redis", None)
    monkeypatch.setattr(celery_app, "dlq_fallback_path", str(fallback))
    retry = Mock(wraps=case.task.retry)
    monkeypatch.setattr(case.task, "retry", retry)
    retry_count = case.task.max_retries if error_type in (ProviderTimeoutError, RateLimitError) else 0
    # When Celery's trace executes the task, terminal failure signal, and runner.
    result = case.task.apply(args=case.args, task_id="surface-failure", retries=retry_count, throw=False)
    # Then stored summaries retain the actionable taxonomy without exception text.
    assert result.state == "FAILURE"
    persisted = fallback.read_text()
    assert len(persisted.splitlines()) == 1
    payload = json.loads(persisted)
    assert payload["failure"]["category"] == category
    assert payload["failure"]["retryable"] is retryable
    assert result.result is error
    assert case.provider.generate.await_count + case.provider.transcribe.await_count == 1
    if error_type not in (ProviderTimeoutError, RateLimitError):
        retry.assert_not_called()
    assert "synthetic-private-value" not in persisted
    assert "secret.invalid" not in persisted
    assert "Traceback" not in persisted

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
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            path = f"/api/creator/runs/{case.runner.run_id}/tasks"
            response = await client.get(path, headers={"X-API-Key": "owner"})
            assert response.status_code == 200
            task = response.json()[0]
            assert (task["status"], task["error_code"]) == ("failed", category)
            assert task["failure"] == payload["failure"]
            assert task["error_message"] == payload["exception"]
            assert "synthetic-private-value" not in response.text
            assert "secret.invalid" not in response.text
            if category == "PROVIDER_AUTH":
                assert any("API key" in step for step in task["failure"]["recovery_steps"])
            foreign = await client.get(path, headers={"X-API-Key": "other"})
            absent = await client.get("/api/creator/runs/999999/tasks", headers={"X-API-Key": "owner"})
            assert foreign.status_code == absent.status_code == 404
            assert foreign.json() == absent.json() == {"detail": "Not found"}
            assert (await client.get(path)).status_code == 401

    run_in_worker_loop(verify_http())
