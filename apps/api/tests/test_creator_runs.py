# pyright: reportMissingImports=false

from datetime import datetime, timezone
from typing import Literal

import pytest
from pydantic import BaseModel

from shorts_api.main import runs_router


class StubPipelineRun(BaseModel):
    id: int
    project_id: int
    current_stage: str | None = None
    status: Literal["pending", "running", "paused", "completed", "failed", "cancelled"] = "pending"
    review_stage: str | None = None
    restart_from: str | None = None
    model_defaults: dict[str, str] | None = None
    metadata: dict[str, object] | None = None
    style_preset: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class StubRunService:
    def __init__(self) -> None:
        self.create_run_calls: list[dict[str, object]] = []
        self.get_run_calls: list[int] = []
        self.restart_run_calls: list[dict[str, object]] = []
        self.runs: dict[int, StubPipelineRun] = {}
        self._next_id = 1

    async def create_run(
        self,
        project_id: int,
        model_defaults: dict[str, str] | None,
        style_preset: str,
        metadata: dict[str, object] | None,
    ) -> StubPipelineRun:
        self.create_run_calls.append(
            {
                "project_id": project_id,
                "model_defaults": model_defaults,
                "style_preset": style_preset,
                "metadata": metadata,
            }
        )

        now = datetime.now(timezone.utc)
        run = StubPipelineRun(
            id=self._next_id,
            project_id=project_id,
            current_stage="IDEA_READY",
            status="pending",
            review_stage=None,
            restart_from=None,
            model_defaults=model_defaults,
            metadata=metadata,
            style_preset=style_preset,
            started_at=None,
            finished_at=None,
            created_at=now,
            updated_at=now,
        )
        self.runs[self._next_id] = run
        self._next_id += 1
        return run

    async def get_run(self, run_id: int) -> StubPipelineRun | None:
        self.get_run_calls.append(run_id)
        return self.runs.get(run_id)

    async def restart_run(self, run_id: int, from_stage: str) -> StubPipelineRun:
        self.restart_run_calls.append({"run_id": run_id, "from_stage": from_stage})

        run = self.runs.get(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        if from_stage not in {"SCRIPT_GENERATING", "VISUAL_PLAN_GENERATING"}:
            raise ValueError(f"Invalid stage '{from_stage}'")

        updated = run.model_copy(update={"restart_from": from_stage, "current_stage": from_stage})
        self.runs[run_id] = updated
        return updated


@pytest.fixture
def stub_run_service(monkeypatch: pytest.MonkeyPatch) -> StubRunService:
    service = StubRunService()

    for route in runs_router.routes:
        if route.name in {"create_run", "get_run_detail", "restart_run"}:
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", service)

    return service


@pytest.mark.asyncio
async def test_create_run(client, stub_run_service: StubRunService):
    response = await client.post(
        "/api/creator/projects/7/runs",
        json={
            "model_defaults": {
                "script_model": "qwen3-4b",
                "image_model": "sd15",
            },
            "style_preset": "cinematic",
            "metadata": {"episode": 1},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == 7
    assert body["model_defaults"] == {"script_model": "qwen3-4b", "image_model": "sd15"}
    assert body["style_preset"] == "cinematic"
    assert body["metadata"] == {"episode": 1}
    assert stub_run_service.create_run_calls == [
        {
            "project_id": 7,
            "model_defaults": {"script_model": "qwen3-4b", "image_model": "sd15"},
            "style_preset": "cinematic",
            "metadata": {"episode": 1},
        }
    ]


@pytest.mark.asyncio
async def test_create_run_minimal(client, stub_run_service: StubRunService):
    _ = stub_run_service
    response = await client.post(
        "/api/creator/projects/8/runs",
        json={"style_preset": "default"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == 8
    assert body["model_defaults"] is None
    assert body["metadata"] is None
    assert body["style_preset"] == "default"


@pytest.mark.asyncio
async def test_get_run_found(client, stub_run_service: StubRunService):
    now = datetime.now(timezone.utc)
    stub_run_service.runs[33] = StubPipelineRun(
        id=33,
        project_id=3,
        current_stage="SCRIPT_REVIEW",
        status="running",
        review_stage="SCRIPT_REVIEW",
        restart_from="SCRIPT_GENERATING",
        model_defaults={"script_model": "qwen3-4b", "image_model": "sd15"},
        metadata={"attempt": 2},
        style_preset="dynamic",
        started_at=now,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )

    response = await client.get("/api/creator/runs/33")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 33
    assert body["project_id"] == 3
    assert body["current_stage"] == "SCRIPT_REVIEW"
    assert body["status"] == "running"
    assert body["review_stage"] == "SCRIPT_REVIEW"
    assert body["restart_from"] == "SCRIPT_GENERATING"
    assert body["model_defaults"] == {"script_model": "qwen3-4b", "image_model": "sd15"}
    assert body["metadata"] == {"attempt": 2}
    assert body["style_preset"] == "dynamic"
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_get_run_not_found(client, stub_run_service: StubRunService):
    _ = stub_run_service
    response = await client.get("/api/creator/runs/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


@pytest.mark.asyncio
async def test_restart_run_valid(client, stub_run_service: StubRunService):
    now = datetime.now(timezone.utc)
    stub_run_service.runs[4] = StubPipelineRun(
        id=4,
        project_id=1,
        current_stage="IDEA_READY",
        status="pending",
        review_stage=None,
        restart_from=None,
        model_defaults=None,
        metadata=None,
        style_preset="default",
        started_at=None,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )

    response = await client.post("/api/creator/runs/4/restart", json={"stage": "SCRIPT_GENERATING"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 4
    assert body["current_stage"] == "SCRIPT_GENERATING"
    assert body["restart_from"] == "SCRIPT_GENERATING"
    assert stub_run_service.restart_run_calls == [{"run_id": 4, "from_stage": "SCRIPT_GENERATING"}]


@pytest.mark.asyncio
async def test_restart_run_invalid_stage(client, stub_run_service: StubRunService):
    now = datetime.now(timezone.utc)
    stub_run_service.runs[5] = StubPipelineRun(
        id=5,
        project_id=2,
        current_stage="IDEA_READY",
        status="pending",
        review_stage=None,
        restart_from=None,
        model_defaults=None,
        metadata=None,
        style_preset="default",
        started_at=None,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )

    response = await client.post("/api/creator/runs/5/restart", json={"stage": "INVALID_STAGE"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid stage 'INVALID_STAGE'"}


@pytest.mark.asyncio
async def test_restart_run_not_found(client, stub_run_service: StubRunService):
    _ = stub_run_service
    response = await client.post("/api/creator/runs/4242/restart", json={"stage": "SCRIPT_GENERATING"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Run 4242 not found"}
