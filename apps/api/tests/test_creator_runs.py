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
        self.advance_stage_calls: list[dict[str, object]] = []
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

    async def advance_stage(self, run_id: int, target_stage: str) -> StubPipelineRun:
        self.advance_stage_calls.append({"run_id": run_id, "target_stage": target_stage})

        run = self.runs.get(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        if target_stage not in {"SCRIPT_GENERATING", "VISUAL_PLAN_GENERATING"}:
            raise ValueError(f"Invalid stage '{target_stage}'")

        updated = run.model_copy(update={"current_stage": target_stage})
        self.runs[run_id] = updated
        return updated

class StubStageReviewService:
    def __init__(self) -> None:
        self.record_approval_calls: list[dict[str, object]] = []

    async def record_approval(
        self, run_id: int, stage_name: str, reviewer: str = "agent", notes: str | None = None
    ) -> dict[str, object]:
        self.record_approval_calls.append(
            {"run_id": run_id, "stage_name": stage_name, "reviewer": reviewer, "notes": notes}
        )
        return {
            "id": len(self.record_approval_calls),
            "run_id": run_id,
            "stage_name": stage_name,
            "review_status": "approved",
            "reviewer": reviewer,
            "notes": notes,
            "created_at": datetime.now(timezone.utc),
        }


@pytest.fixture
def stub_run_service(monkeypatch: pytest.MonkeyPatch) -> StubRunService:
    service = StubRunService()

    for route in runs_router.routes:
        if route.name in {"create_run", "get_run_detail", "restart_run", "approve_script"}:
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

    assert response.status_code == 404
    assert response.json() == {"detail": "Run 4242 not found"}


@pytest.fixture
def stub_approve_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubStageReviewService]:
    run_svc = StubRunService()
    review_svc = StubStageReviewService()

    for route in runs_router.routes:
        if route.name == "approve_script":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "stage_review_service", review_svc)

    return run_svc, review_svc


def _make_run(run_id: int, stage: str = "SCRIPT_REVIEW") -> StubPipelineRun:
    now = datetime.now(timezone.utc)
    return StubPipelineRun(
        id=run_id,
        project_id=1,
        current_stage=stage,
        status="running",
        review_stage=stage if stage == "SCRIPT_REVIEW" else None,
        restart_from=None,
        model_defaults=None,
        metadata=None,
        style_preset="default",
        started_at=now,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_approve_script_success(client, stub_approve_services):
    run_svc, review_svc = stub_approve_services
    run_svc.runs[10] = _make_run(10, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/10/approve-script",
        json={"reviewer": "human", "notes": "Looks good"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 10
    assert body["current_stage"] == "VISUAL_PLAN_GENERATING"
    assert review_svc.record_approval_calls == [
        {"run_id": 10, "stage_name": "SCRIPT_REVIEW", "reviewer": "human", "notes": "Looks good"}
    ]
    assert run_svc.advance_stage_calls == [{"run_id": 10, "target_stage": "VISUAL_PLAN_GENERATING"}]


@pytest.mark.asyncio
async def test_approve_script_default_reviewer(client, stub_approve_services):
    run_svc, review_svc = stub_approve_services
    run_svc.runs[11] = _make_run(11, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/11/approve-script",
        json={},
    )

    assert response.status_code == 200
    assert review_svc.record_approval_calls[0]["reviewer"] == "agent"
    assert review_svc.record_approval_calls[0]["notes"] is None


@pytest.mark.asyncio
async def test_approve_script_run_not_found(client, stub_approve_services):
    _, _ = stub_approve_services
    response = await client.post(
        "/api/creator/runs/999/approve-script",
        json={},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


@pytest.mark.asyncio
async def test_approve_script_wrong_stage(client, stub_approve_services):
    run_svc, _ = stub_approve_services
    run_svc.runs[12] = _make_run(12, "IDEA_READY")

    response = await client.post(
        "/api/creator/runs/12/approve-script",
        json={},
    )

    assert response.status_code == 400
    assert "expected 'SCRIPT_REVIEW'" in response.json()["detail"]


@pytest.mark.asyncio
async def test_approve_script_wrong_stage_generating(client, stub_approve_services):
    run_svc, _ = stub_approve_services
    run_svc.runs[13] = _make_run(13, "SCRIPT_GENERATING")

    response = await client.post(
        "/api/creator/runs/13/approve-script",
        json={},
    )

    assert response.status_code == 400
    assert "SCRIPT_GENERATING" in response.json()["detail"]
