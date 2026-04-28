from datetime import datetime, timezone

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel
from shorts_api.main import app


class StubRun(BaseModel):
    id: int


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


class StubRunService:
    async def get_run(self, run_id: int) -> StubRun | None:
        if run_id == 1:
            return StubRun(id=1)
        return None


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


@pytest.fixture
def stub_services(monkeypatch: pytest.MonkeyPatch) -> None:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.name == "list_run_tasks":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", StubRunService())
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "task_tracking_service",
                StubTaskTrackingService(),
            )


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
