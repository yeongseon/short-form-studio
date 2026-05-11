from datetime import datetime, timezone

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel
from shorts_api.auth import CurrentUser, require_run_access
from shorts_api.main import app


class StubRun(BaseModel):
    id: int
    project_id: int = 1


class StubTask(BaseModel):
    id: int
    run_id: int
    task_type: str
    celery_task_id: str
    status: str
    attempt: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime


class StubTaskTrackingService:
    async def list_run_tasks(self, run_id: int) -> list[StubTask]:
        now = datetime.now(timezone.utc)
        return [
            StubTask(
                id=2,
                run_id=run_id,
                task_type="generate_audio",
                celery_task_id="celery-2",
                status="success",
                attempt=1,
                finished_at=now,
                created_at=now,
            ),
            StubTask(
                id=1,
                run_id=run_id,
                task_type="generate_script",
                celery_task_id="celery-1",
                status="failed",
                attempt=1,
                error_code="RuntimeError",
                error_message="boom",
                created_at=now,
            ),
        ]


_runs = {1: StubRun(id=1)}


async def _require_run_access_ok(run_id: int) -> tuple[CurrentUser, StubRun]:
    run = _runs.get(run_id)
    if run is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Run not found")
    return CurrentUser(user_id=1, workspace_id=1), run


@pytest.fixture
def stub_services(monkeypatch: pytest.MonkeyPatch):
    app.dependency_overrides[require_run_access] = _require_run_access_ok

    for route in app.routes:
        if isinstance(route, APIRoute) and route.name == "list_run_tasks":
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "task_tracking_service",
                StubTaskTrackingService(),
            )

    yield

    app.dependency_overrides.pop(require_run_access, None)


@pytest.mark.asyncio
async def test_get_run_tasks_returns_task_list(client, stub_services) -> None:
    _ = stub_services
    response = await client.get("/api/creator/runs/1/tasks")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["celery_task_id"] == "celery-2"
    assert body[1]["error_code"] == "RuntimeError"


@pytest.mark.asyncio
async def test_get_run_tasks_nonexistent_run_returns_404(client, stub_services) -> None:
    _ = stub_services
    response = await client.get("/api/creator/runs/999/tasks")
    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


@pytest.mark.asyncio
async def test_get_run_tasks_requires_authentication(client) -> None:
    """Without dependency override, the real require_run_access should reject."""
    # Remove any override to test real auth path
    app.dependency_overrides.pop(require_run_access, None)

    response = await client.get("/api/creator/runs/1/tasks")
    # Real auth will fail since no API key is provided in test
    assert response.status_code in (401, 403, 404)
