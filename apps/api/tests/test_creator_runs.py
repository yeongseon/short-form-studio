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
    def __init__(self, run_svc: StubRunService) -> None:
        self.approve_calls: list[dict[str, object]] = []
        self._run_svc = run_svc

    async def approve_and_advance(
        self,
        *,
        run_service: object,
        run_id: int,
        stage_name: str,
        target_stage: str,
        reviewer: str = "agent",
        notes: str | None = None,
    ) -> StubPipelineRun:
        self.approve_calls.append({
            "run_id": run_id,
            "stage_name": stage_name,
            "target_stage": target_stage,
            "reviewer": reviewer,
            "notes": notes,
        })

        run = self._run_svc.runs.get(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        if run.current_stage != stage_name:
            raise ValueError(
                f"Stage conflict: run is now in '{run.current_stage}', "
                f"expected '{stage_name}'"
            )

        updated = run.model_copy(update={"current_stage": target_stage})
        self._run_svc.runs[run_id] = updated
        return updated

@pytest.fixture
def stub_run_service(monkeypatch: pytest.MonkeyPatch) -> StubRunService:
    service = StubRunService()

    for route in runs_router.routes:
        if route.name in {"create_run", "get_run_detail", "restart_run", "approve_script", "generate_script_trigger"}:
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
    review_svc = StubStageReviewService(run_svc)

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
    assert review_svc.approve_calls == [
        {
            "run_id": 10,
            "stage_name": "SCRIPT_REVIEW",
            "target_stage": "VISUAL_PLAN_GENERATING",
            "reviewer": "human",
            "notes": "Looks good",
        }
    ]

@pytest.mark.asyncio
async def test_approve_script_default_reviewer(client, stub_approve_services):
    run_svc, review_svc = stub_approve_services
    run_svc.runs[11] = _make_run(11, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/11/approve-script",
        json={},
    )

    assert response.status_code == 200
    assert review_svc.approve_calls[0]["reviewer"] == "agent"
    assert review_svc.approve_calls[0]["notes"] is None

@pytest.mark.asyncio
async def test_approve_script_run_not_found(client, stub_approve_services):
    _, _ = stub_approve_services
    response = await client.post(
        "/api/creator/runs/999/approve-script",
        json={},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_approve_script_wrong_stage(client, stub_approve_services):
    run_svc, _ = stub_approve_services
    run_svc.runs[12] = _make_run(12, "IDEA_READY")

    response = await client.post(
        "/api/creator/runs/12/approve-script",
        json={},
    )

    assert response.status_code == 409
    assert "conflict" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_approve_script_wrong_stage_generating(client, stub_approve_services):
    run_svc, _ = stub_approve_services
    run_svc.runs[13] = _make_run(13, "SCRIPT_GENERATING")

    response = await client.post(
        "/api/creator/runs/13/approve-script",
        json={},
    )

    assert response.status_code == 409
    assert "conflict" in response.json()["detail"].lower()


class StubProject(BaseModel):
    id: int
    title: str | None = None
    source_type: str = "idea"
    idea_brief: str | None = None
    markdown_source: str | None = None
    url_source: str | None = None
    status: str = "draft"
    created_at: datetime
    updated_at: datetime


class StubProjectService:
    def __init__(self) -> None:
        self.projects: dict[int, StubProject] = {}

    async def get_project(self, project_id: int) -> StubProject | None:
        return self.projects.get(project_id)


class StubDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.task_id = "test-task-id-123"

    def __call__(
        self, run_id: int, idea_brief: str, model_key: str, instructions: str | None
    ) -> str:
        self.calls.append({
            "run_id": run_id,
            "idea_brief": idea_brief,
            "model_key": model_key,
            "instructions": instructions,
        })
        return self.task_id


@pytest.fixture
def stub_generate_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubProjectService, StubDispatcher]:
    run_svc = StubRunService()
    project_svc = StubProjectService()
    dispatcher = StubDispatcher()

    for route in runs_router.routes:
        if route.name == "generate_script_trigger":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", project_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "dispatch_generate_script", dispatcher)

    return run_svc, project_svc, dispatcher


def _make_project(project_id: int, idea_brief: str = "Test idea") -> StubProject:
    now = datetime.now(timezone.utc)
    return StubProject(
        id=project_id,
        title="Test Project",
        source_type="idea",
        idea_brief=idea_brief,
        status="draft",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_generate_script_from_idea_ready(client, stub_generate_services):
    run_svc, project_svc, dispatcher = stub_generate_services
    run_svc.runs[10] = _make_run(10, "IDEA_READY")
    project_svc.projects[1] = _make_project(1, "Create a cooking tutorial")

    response = await client.post(
        "/api/creator/runs/10/generate-script",
        json={"model_key": "qwen3-4b", "instructions": "Focus on pasta"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "test-task-id-123"
    assert body["run_id"] == 10
    assert body["current_stage"] == "SCRIPT_GENERATING"
    assert run_svc.advance_stage_calls == [{"run_id": 10, "target_stage": "SCRIPT_GENERATING"}]
    assert len(run_svc.restart_run_calls) == 0
    assert dispatcher.calls == [{
        "run_id": 10,
        "idea_brief": "Create a cooking tutorial",
        "model_key": "qwen3-4b",
        "instructions": "Focus on pasta",
    }]


@pytest.mark.asyncio
async def test_generate_script_from_script_review(client, stub_generate_services):
    run_svc, project_svc, dispatcher = stub_generate_services
    run_svc.runs[11] = _make_run(11, "SCRIPT_REVIEW")
    project_svc.projects[1] = _make_project(1, "Science explainer")

    response = await client.post(
        "/api/creator/runs/11/generate-script",
        json={"model_key": "qwen3-4b"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["current_stage"] == "SCRIPT_GENERATING"
    assert len(run_svc.restart_run_calls) == 1
    assert run_svc.restart_run_calls[0] == {"run_id": 11, "from_stage": "SCRIPT_GENERATING"}
    assert len(run_svc.advance_stage_calls) == 0
    assert dispatcher.calls[0]["idea_brief"] == "Science explainer"


@pytest.mark.asyncio
async def test_generate_script_default_model(client, stub_generate_services):
    run_svc, project_svc, dispatcher = stub_generate_services
    run_svc.runs[12] = _make_run(12, "IDEA_READY")
    project_svc.projects[1] = _make_project(1, "My idea")

    response = await client.post(
        "/api/creator/runs/12/generate-script",
        json={},
    )

    assert response.status_code == 202
    assert dispatcher.calls[0]["model_key"] == "qwen3-4b"
    assert dispatcher.calls[0]["instructions"] is None


@pytest.mark.asyncio
async def test_generate_script_run_not_found(client, stub_generate_services):
    _, _, _ = stub_generate_services
    response = await client.post(
        "/api/creator/runs/999/generate-script",
        json={},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_script_wrong_stage_generating(client, stub_generate_services):
    run_svc, _, _ = stub_generate_services
    run_svc.runs[14] = _make_run(14, "SCRIPT_GENERATING")

    response = await client.post(
        "/api/creator/runs/14/generate-script",
        json={},
    )

    assert response.status_code == 400
    assert "SCRIPT_GENERATING" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_script_wrong_stage_visual(client, stub_generate_services):
    run_svc, _, _ = stub_generate_services
    run_svc.runs[15] = _make_run(15, "VISUAL_PLAN_GENERATING")

    response = await client.post(
        "/api/creator/runs/15/generate-script",
        json={},
    )

    assert response.status_code == 400
    assert "VISUAL_PLAN_GENERATING" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_script_idea_brief_fallback_to_title(client, stub_generate_services):
    run_svc, project_svc, dispatcher = stub_generate_services
    run_svc.runs[16] = _make_run(16, "IDEA_READY")
    now = datetime.now(timezone.utc)
    project_svc.projects[1] = StubProject(
        id=1, title="Fallback Title", idea_brief=None,
        created_at=now, updated_at=now,
    )

    response = await client.post(
        "/api/creator/runs/16/generate-script",
        json={},
    )

    assert response.status_code == 202
    assert dispatcher.calls[0]["idea_brief"] == "Fallback Title"
