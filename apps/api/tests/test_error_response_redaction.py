"""Exercise redaction through the production HTTP handler and task route."""

from datetime import datetime, timezone

import pytest
from creator_domain.exceptions import VersionConflictError
from creator_domain.models.pipeline_run import PipelineRun
from creator_domain.models.run_task import RunTask
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from shorts_api.app_factory import create_app
from shorts_api.auth import CurrentUser, require_run_access
from shorts_api.routes import creator_run_tasks


@pytest.mark.parametrize("resource_id", ["sk-syntheticConflict123456", "/home/synthetic/private", "https://synthetic.invalid/private"])
@pytest.mark.asyncio
async def test_version_conflict_redacts_nested_resource_id(resource_id: str) -> None:
    # Given: the real app exception handler with an unsafe string resource id.
    app = create_app()

    @app.get("/test/redaction-conflict")
    async def conflict() -> None:
        raise VersionConflictError(resource_id, 3, 5)

    # When
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/test/redaction-conflict")
    # Then: both detail and nested metadata are protected on the wire.
    assert response.status_code == 409
    assert resource_id not in response.text
    assert response.json()["error"]["version_conflict"] == {
        "resource_id": "<redacted>", "expected_version": 3, "actual_version": 5,
    }


@pytest.mark.parametrize("code", ["PROVIDER_AUTH", "UNAVAILABLE", "ValueError", None])
@pytest.mark.asyncio
async def test_task_http_hides_legacy_message(
    monkeypatch: pytest.MonkeyPatch, code: str | None
) -> None:
    # Given: real domain tasks with legacy traceback/message data.
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    raw = "Traceback (most recent call last): synthetic-legacy-private-value"
    task = RunTask(id=1, run_id=1, task_type="generate_script", celery_task_id="task-1",
                   status="failed", error_code=code, error_message=raw, created_at=now)

    async def tasks(run_id: int) -> list[RunTask]:
        return [task]

    async def access(run_id: int) -> tuple[CurrentUser, PipelineRun]:
        if run_id != 1:
            raise HTTPException(status_code=404, detail="Run not found")
        return CurrentUser(user_id=1, workspace_id=1), PipelineRun(
            id=1, project_id=1, created_at=now, updated_at=now,
        )

    app = FastAPI()
    app.include_router(creator_run_tasks.router, prefix="/api/creator")
    app.dependency_overrides[require_run_access] = access
    monkeypatch.setattr(creator_run_tasks.task_tracking_service, "list_run_tasks", tasks)
    # When
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/creator/runs/1/tasks")
    # Then
    assert response.status_code == 200
    assert "synthetic-legacy-private-value" not in response.text
    assert "Traceback" not in response.text
    item = response.json()[0]
    expected_code = code if code in ("PROVIDER_AUTH", "UNAVAILABLE") else "INTERNAL"
    assert item["failure"]["code"] == expected_code
    assert item["error_message"] == item["failure"]["message"]
    assert task.error_message == raw  # Read-side sanitization must not mutate storage.
