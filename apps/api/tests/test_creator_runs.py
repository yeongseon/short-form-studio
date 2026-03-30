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
        self.storage = StubRunStorage(self)
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

    async def list_runs_by_project(self, project_id: int) -> list[StubPipelineRun]:
        return sorted(
            [r for r in self.runs.values() if r.project_id == project_id],
            key=lambda r: r.id,
            reverse=True,
        )


class StubRunStorage:
    """Minimal storage stub that supports conditional_update_run."""

    def __init__(self, run_svc: "StubRunService") -> None:
        self._run_svc = run_svc
        self.conditional_update_calls: list[dict[str, object]] = []

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, object],
        expected_stages: frozenset[str],
    ) -> tuple[bool, dict[str, object] | None]:
        self.conditional_update_calls.append({
            "run_id": run_id,
            "updates": dict(updates),
            "expected_stages": expected_stages,
        })

        run = self._run_svc.runs.get(run_id)
        if run is None:
            return False, None
        if run.current_stage not in expected_stages:
            return False, run.model_dump(mode="json")

        updated = run.model_copy(update=updates)
        self._run_svc.runs[run_id] = updated
        return True, updated.model_dump(mode="json")
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
        if route.name in {"create_run", "get_run_detail", "restart_run", "approve_script", "generate_script_trigger", "generate_visual_plan_trigger", "generate_audio_trigger", "generate_subtitles_trigger", "list_runs_for_project"}:
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


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/approve-visual-plan
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_approve_vp_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubStageReviewService]:
    run_svc = StubRunService()
    review_svc = StubStageReviewService(run_svc)

    for route in runs_router.routes:
        if route.name == "approve_visual_plan":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "stage_review_service", review_svc)

    return run_svc, review_svc


def _make_vp_run(run_id: int, stage: str = "VISUAL_PLAN_REVIEW") -> StubPipelineRun:
    now = datetime.now(timezone.utc)
    return StubPipelineRun(
        id=run_id,
        project_id=1,
        current_stage=stage,
        status="running",
        review_stage=stage if stage == "VISUAL_PLAN_REVIEW" else None,
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
async def test_approve_visual_plan_success(client, stub_approve_vp_services):
    run_svc, review_svc = stub_approve_vp_services
    run_svc.runs[50] = _make_vp_run(50, "VISUAL_PLAN_REVIEW")

    response = await client.post(
        "/api/creator/runs/50/approve-visual-plan",
        json={"reviewer": "human", "notes": "Visual plan approved"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 50
    assert body["current_stage"] == "VISUAL_ASSET_GENERATING"
    assert review_svc.approve_calls == [
        {
            "run_id": 50,
            "stage_name": "VISUAL_PLAN_REVIEW",
            "target_stage": "VISUAL_ASSET_GENERATING",
            "reviewer": "human",
            "notes": "Visual plan approved",
        }
    ]


@pytest.mark.asyncio
async def test_approve_visual_plan_default_reviewer(client, stub_approve_vp_services):
    run_svc, review_svc = stub_approve_vp_services
    run_svc.runs[51] = _make_vp_run(51, "VISUAL_PLAN_REVIEW")

    response = await client.post(
        "/api/creator/runs/51/approve-visual-plan",
        json={},
    )

    assert response.status_code == 200
    assert review_svc.approve_calls[0]["reviewer"] == "agent"
    assert review_svc.approve_calls[0]["notes"] is None


@pytest.mark.asyncio
async def test_approve_visual_plan_run_not_found(client, stub_approve_vp_services):
    _, _ = stub_approve_vp_services
    response = await client.post(
        "/api/creator/runs/999/approve-visual-plan",
        json={},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approve_visual_plan_wrong_stage(client, stub_approve_vp_services):
    run_svc, _ = stub_approve_vp_services
    run_svc.runs[52] = _make_vp_run(52, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/52/approve-visual-plan",
        json={},
    )

    assert response.status_code == 409
    assert "conflict" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approve_visual_plan_wrong_stage_generating(client, stub_approve_vp_services):
    run_svc, _ = stub_approve_vp_services
    run_svc.runs[53] = _make_vp_run(53, "VISUAL_PLAN_GENERATING")

    response = await client.post(
        "/api/creator/runs/53/approve-visual-plan",
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
    # CAS was called for IDEA_READY → SCRIPT_GENERATING (no restart_from)
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 10
    assert cas_calls[0]["updates"] == {"current_stage": "SCRIPT_GENERATING"}
    assert "IDEA_READY" in cas_calls[0]["expected_stages"]
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
    # CAS was called for SCRIPT_REVIEW → SCRIPT_GENERATING with restart_from
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 11
    assert cas_calls[0]["updates"] == {
        "current_stage": "SCRIPT_GENERATING",
        "restart_from": "SCRIPT_GENERATING",
    }
    assert "SCRIPT_REVIEW" in cas_calls[0]["expected_stages"]
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


@pytest.mark.asyncio
async def test_generate_script_cas_conflict(client, stub_generate_services):
    """CAS fails because stage changed between initial check and CAS."""
    run_svc, project_svc, dispatcher = stub_generate_services
    # Set stage to IDEA_READY so the initial check passes
    run_svc.runs[20] = _make_run(20, "IDEA_READY")
    project_svc.projects[1] = _make_project(1, "Conflict test")

    # Simulate a concurrent stage change: after the initial read, change stage
    # so CAS will find mismatch.  We do this by mutating the run between the
    # initial get_run and the CAS call.  Because the route reads once then CAS,
    # we override conditional_update_run to simulate conflict.

    async def cas_conflict(run_id, updates, expected_stages):
        # Return conflict: stage changed to SCRIPT_GENERATING
        return False, {"current_stage": "SCRIPT_GENERATING", "id": run_id}

    run_svc.storage.conditional_update_run = cas_conflict

    response = await client.post(
        "/api/creator/runs/20/generate-script",
        json={},
    )

    assert response.status_code == 409
    assert "conflict" in response.json()["detail"].lower()
    # Dispatcher was NOT called
    assert len(dispatcher.calls) == 0


@pytest.mark.asyncio
async def test_generate_script_dispatch_failure_rollback(client, stub_generate_services):
    """Celery dispatch failure triggers rollback to original stage."""
    run_svc, project_svc, _ = stub_generate_services
    run_svc.runs[21] = _make_run(21, "IDEA_READY")
    project_svc.projects[1] = _make_project(1, "Dispatch fail test")

    def failing_dispatcher(run_id, idea_brief, model_key, instructions):
        raise RuntimeError("Celery broker down")

    # Patch the dispatcher for this test
    from shorts_api.main import runs_router as _r
    for route in _r.routes:
        if route.name == "generate_script_trigger":
            route.endpoint.__globals__["dispatch_generate_script"] = failing_dispatcher

    response = await client.post(
        "/api/creator/runs/21/generate-script",
        json={},
    )

    assert response.status_code == 503
    assert "enqueue" in response.json()["detail"].lower()

    # Rollback: CAS was called twice — first to advance, then to rollback
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 2
    # Second CAS = rollback to IDEA_READY
    rollback = cas_calls[1]
    assert rollback["updates"]["current_stage"] == "IDEA_READY"
    assert rollback["expected_stages"] == frozenset({"SCRIPT_GENERATING"})

    # Verify run was actually rolled back to IDEA_READY
    assert run_svc.runs[21].current_stage == "IDEA_READY"


@pytest.mark.asyncio
async def test_generate_script_project_not_found(client, stub_generate_services):
    """Project not found returns 404 BEFORE any state mutation."""
    run_svc, project_svc, dispatcher = stub_generate_services
    run_svc.runs[22] = _make_run(22, "IDEA_READY")
    # Do NOT add project — project_svc.projects is empty

    response = await client.post(
        "/api/creator/runs/22/generate-script",
        json={},
    )

    assert response.status_code == 404
    assert "project" in response.json()["detail"].lower()
    # No CAS call — precondition failed before mutation
    assert len(run_svc.storage.conditional_update_calls) == 0
    # No dispatch
    assert len(dispatcher.calls) == 0


@pytest.mark.asyncio
async def test_list_runs_for_project(client, stub_run_service: StubRunService):
    # Create 2 runs for project 7 and 1 for project 8
    await stub_run_service.create_run(project_id=7, model_defaults=None, style_preset="default", metadata=None)
    await stub_run_service.create_run(project_id=7, model_defaults=None, style_preset="default", metadata=None)
    await stub_run_service.create_run(project_id=8, model_defaults=None, style_preset="default", metadata=None)

    response = await client.get("/api/creator/projects/7/runs")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["runs"]) == 2
    # Newest first
    assert body["runs"][0]["id"] > body["runs"][1]["id"]
    assert all(r["project_id"] == 7 for r in body["runs"])


@pytest.mark.asyncio
async def test_list_runs_for_project_empty(client, stub_run_service: StubRunService):
    _ = stub_run_service
    response = await client.get("/api/creator/projects/999/runs")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["runs"] == []


class StubVisualPlanDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.task_id = "test-vp-task-id-456"

    def __call__(
        self, run_id: int, model_key: str, style_preset: str | None
    ) -> str:
        self.calls.append({
            "run_id": run_id,
            "model_key": model_key,
            "style_preset": style_preset,
        })
        return self.task_id


@pytest.fixture
def stub_generate_visual_plan_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubVisualPlanDispatcher]:
    run_svc = StubRunService()
    dispatcher = StubVisualPlanDispatcher()

    for route in runs_router.routes:
        if route.name == "generate_visual_plan_trigger":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "dispatch_generate_visual_plan", dispatcher)

    return run_svc, dispatcher


@pytest.mark.asyncio
async def test_generate_visual_plan_from_script_review(client, stub_generate_visual_plan_services):
    run_svc, dispatcher = stub_generate_visual_plan_services
    run_svc.runs[30] = _make_run(30, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/30/generate-visual-plan",
        json={"model_key": "qwen3-4b", "style_preset": "cinematic"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "test-vp-task-id-456"
    assert body["run_id"] == 30
    assert body["current_stage"] == "VISUAL_PLAN_GENERATING"
    # CAS was called for SCRIPT_REVIEW → VISUAL_PLAN_GENERATING (no restart_from)
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 30
    assert cas_calls[0]["updates"] == {"current_stage": "VISUAL_PLAN_GENERATING"}
    assert "SCRIPT_REVIEW" in cas_calls[0]["expected_stages"]
    assert dispatcher.calls == [{
        "run_id": 30,
        "model_key": "qwen3-4b",
        "style_preset": "cinematic",
    }]


@pytest.mark.asyncio
async def test_generate_visual_plan_retry_from_generating(client, stub_generate_visual_plan_services):
    run_svc, dispatcher = stub_generate_visual_plan_services
    run_svc.runs[31] = _make_run(31, "VISUAL_PLAN_GENERATING")

    response = await client.post(
        "/api/creator/runs/31/generate-visual-plan",
        json={"model_key": "qwen3-4b"},
    )

    assert response.status_code == 202
    # CAS was called for VISUAL_PLAN_GENERATING → VISUAL_PLAN_GENERATING with restart_from
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 31
    assert cas_calls[0]["updates"] == {
        "current_stage": "VISUAL_PLAN_GENERATING",
        "restart_from": "VISUAL_PLAN_GENERATING",
    }
    assert "VISUAL_PLAN_GENERATING" in cas_calls[0]["expected_stages"]
    assert len(dispatcher.calls) == 1


@pytest.mark.asyncio
async def test_generate_visual_plan_default_model(client, stub_generate_visual_plan_services):
    run_svc, dispatcher = stub_generate_visual_plan_services
    run_svc.runs[32] = _make_run(32, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/32/generate-visual-plan",
        json={},
    )

    assert response.status_code == 202
    assert dispatcher.calls[0]["model_key"] == "qwen3-4b"
    assert dispatcher.calls[0]["style_preset"] is None


@pytest.mark.asyncio
async def test_generate_visual_plan_run_not_found(client, stub_generate_visual_plan_services):
    _, _ = stub_generate_visual_plan_services
    response = await client.post(
        "/api/creator/runs/999/generate-visual-plan",
        json={},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_visual_plan_wrong_stage(client, stub_generate_visual_plan_services):
    run_svc, _ = stub_generate_visual_plan_services
    run_svc.runs[33] = _make_run(33, "IDEA_READY")

    response = await client.post(
        "/api/creator/runs/33/generate-visual-plan",
        json={},
    )

    assert response.status_code == 400
    assert "IDEA_READY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_visual_plan_wrong_stage_visual_review(client, stub_generate_visual_plan_services):
    run_svc, _ = stub_generate_visual_plan_services
    run_svc.runs[34] = _make_run(34, "VISUAL_PLAN_REVIEW")

    response = await client.post(
        "/api/creator/runs/34/generate-visual-plan",
        json={},
    )

    assert response.status_code == 400
    assert "VISUAL_PLAN_REVIEW" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_visual_plan_cas_conflict(client, stub_generate_visual_plan_services):
    """CAS fails because stage changed between initial check and CAS."""
    run_svc, dispatcher = stub_generate_visual_plan_services
    run_svc.runs[35] = _make_run(35, "SCRIPT_REVIEW")

    async def cas_conflict(run_id, updates, expected_stages):
        return False, {"current_stage": "VISUAL_PLAN_GENERATING", "id": run_id}

    run_svc.storage.conditional_update_run = cas_conflict

    response = await client.post(
        "/api/creator/runs/35/generate-visual-plan",
        json={},
    )

    assert response.status_code == 409
    assert "conflict" in response.json()["detail"].lower()
    assert len(dispatcher.calls) == 0


@pytest.mark.asyncio
async def test_generate_visual_plan_dispatch_failure_rollback(client, stub_generate_visual_plan_services):
    """Celery dispatch failure triggers rollback to original stage."""
    run_svc, _ = stub_generate_visual_plan_services
    run_svc.runs[36] = _make_run(36, "SCRIPT_REVIEW")

    def failing_dispatcher(run_id, model_key, style_preset):
        raise RuntimeError("Celery broker down")

    from shorts_api.main import runs_router as _r
    for route in _r.routes:
        if route.name == "generate_visual_plan_trigger":
            route.endpoint.__globals__["dispatch_generate_visual_plan"] = failing_dispatcher

    response = await client.post(
        "/api/creator/runs/36/generate-visual-plan",
        json={},
    )

    assert response.status_code == 503
    assert "enqueue" in response.json()["detail"].lower()

    # Rollback: CAS was called twice — first to advance, then to rollback
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 2
    # Second CAS = rollback to SCRIPT_REVIEW
    rollback = cas_calls[1]
    assert rollback["updates"]["current_stage"] == "SCRIPT_REVIEW"
    assert rollback["expected_stages"] == frozenset({"VISUAL_PLAN_GENERATING"})

    # Verify run was actually rolled back to SCRIPT_REVIEW
    assert run_svc.runs[36].current_stage == "SCRIPT_REVIEW"




# -- generate-visual-assets tests -----------------------------------------------




class StubImageDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.task_id = "test-img-task-id-789"

    def __call__(
        self, run_id: int, model_key: str, scene_id: str | None,
        prompt_override: str | None, is_active: bool,
    ) -> str:
        self.calls.append({
            "run_id": run_id,
            "model_key": model_key,
            "scene_id": scene_id,
            "prompt_override": prompt_override,
            "is_active": is_active,
        })
        return self.task_id


@pytest.fixture
def stub_generate_visual_assets_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubImageDispatcher]:
    run_svc = StubRunService()
    dispatcher = StubImageDispatcher()

    for route in runs_router.routes:
        if route.name == "generate_visual_assets_trigger":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "dispatch_generate_scene_image", dispatcher)

    return run_svc, dispatcher


@pytest.mark.asyncio
async def test_generate_visual_assets_from_visual_plan_review(client, stub_generate_visual_assets_services):
    run_svc, dispatcher = stub_generate_visual_assets_services
    run_svc.runs[60] = _make_run(60, "VISUAL_PLAN_REVIEW")

    response = await client.post(
        "/api/creator/runs/60/generate-visual-assets",
        json={"model_key": "sd15"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "test-img-task-id-789"
    assert body["run_id"] == 60
    assert body["current_stage"] == "VISUAL_ASSET_GENERATING"
    # CAS was called for VISUAL_PLAN_REVIEW → VISUAL_ASSET_GENERATING (no restart_from)
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 60
    assert cas_calls[0]["updates"] == {"current_stage": "VISUAL_ASSET_GENERATING"}
    assert "VISUAL_PLAN_REVIEW" in cas_calls[0]["expected_stages"]
    assert dispatcher.calls == [{
        "run_id": 60,
        "model_key": "sd15",
        "scene_id": None,
        "prompt_override": None,
        "is_active": True,
    }]


@pytest.mark.asyncio
async def test_generate_visual_assets_retry_from_generating(client, stub_generate_visual_assets_services):
    run_svc, dispatcher = stub_generate_visual_assets_services
    run_svc.runs[61] = _make_run(61, "VISUAL_ASSET_GENERATING")

    response = await client.post(
        "/api/creator/runs/61/generate-visual-assets",
        json={"model_key": "sd15"},
    )

    assert response.status_code == 202
    # CAS was called for VISUAL_ASSET_GENERATING → VISUAL_ASSET_GENERATING with restart_from
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 61
    assert cas_calls[0]["updates"] == {
        "current_stage": "VISUAL_ASSET_GENERATING",
        "restart_from": "VISUAL_ASSET_GENERATING",
    }
    assert "VISUAL_ASSET_GENERATING" in cas_calls[0]["expected_stages"]
    assert len(dispatcher.calls) == 1


@pytest.mark.asyncio
async def test_generate_visual_assets_default_model(client, stub_generate_visual_assets_services):
    run_svc, dispatcher = stub_generate_visual_assets_services
    run_svc.runs[62] = _make_run(62, "VISUAL_PLAN_REVIEW")

    response = await client.post(
        "/api/creator/runs/62/generate-visual-assets",
        json={},
    )

    assert response.status_code == 202
    assert dispatcher.calls[0]["model_key"] == "sd15"


@pytest.mark.asyncio
async def test_generate_visual_assets_run_not_found(client, stub_generate_visual_assets_services):
    _, _ = stub_generate_visual_assets_services
    response = await client.post(
        "/api/creator/runs/999/generate-visual-assets",
        json={},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_visual_assets_wrong_stage(client, stub_generate_visual_assets_services):
    run_svc, _ = stub_generate_visual_assets_services
    run_svc.runs[63] = _make_run(63, "IDEA_READY")

    response = await client.post(
        "/api/creator/runs/63/generate-visual-assets",
        json={},
    )

    assert response.status_code == 400
    assert "IDEA_READY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_visual_assets_wrong_stage_script_review(client, stub_generate_visual_assets_services):
    run_svc, _ = stub_generate_visual_assets_services
    run_svc.runs[64] = _make_run(64, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/64/generate-visual-assets",
        json={},
    )

    assert response.status_code == 400
    assert "SCRIPT_REVIEW" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_visual_assets_cas_conflict(client, stub_generate_visual_assets_services):
    """CAS fails because stage changed between initial check and CAS."""
    run_svc, dispatcher = stub_generate_visual_assets_services
    run_svc.runs[65] = _make_run(65, "VISUAL_PLAN_REVIEW")

    async def cas_conflict(run_id, updates, expected_stages):
        return False, {"current_stage": "VISUAL_ASSET_GENERATING", "id": run_id}

    run_svc.storage.conditional_update_run = cas_conflict

    response = await client.post(
        "/api/creator/runs/65/generate-visual-assets",
        json={},
    )

    assert response.status_code == 409
    assert "conflict" in response.json()["detail"].lower()
    assert len(dispatcher.calls) == 0


@pytest.mark.asyncio
async def test_generate_visual_assets_dispatch_failure_rollback(client, stub_generate_visual_assets_services):
    """Celery dispatch failure triggers rollback to original stage."""
    run_svc, _ = stub_generate_visual_assets_services
    run_svc.runs[66] = _make_run(66, "VISUAL_PLAN_REVIEW")

    def failing_dispatcher(run_id, model_key, scene_id, prompt_override, is_active):
        raise RuntimeError("Celery broker down")

    from shorts_api.main import runs_router as _r
    for route in _r.routes:
        if route.name == "generate_visual_assets_trigger":
            route.endpoint.__globals__["dispatch_generate_scene_image"] = failing_dispatcher

    response = await client.post(
        "/api/creator/runs/66/generate-visual-assets",
        json={},
    )

    assert response.status_code == 503
    assert "enqueue" in response.json()["detail"].lower()

    # Rollback: CAS was called twice — first to advance, then to rollback
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 2
    # Second CAS = rollback to VISUAL_PLAN_REVIEW
    rollback = cas_calls[1]
    assert rollback["updates"]["current_stage"] == "VISUAL_PLAN_REVIEW"
    assert rollback["expected_stages"] == frozenset({"VISUAL_ASSET_GENERATING"})

    # Verify run was actually rolled back to VISUAL_PLAN_REVIEW
    assert run_svc.runs[66].current_stage == "VISUAL_PLAN_REVIEW"


# ──────────────────────────────────────────────────────────────────────
# Single-scene generate-image tests (Issue #52)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def stub_single_scene_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubImageDispatcher]:
    run_svc = StubRunService()
    dispatcher = StubImageDispatcher()

    for route in runs_router.routes:
        if route.name in ("generate_scene_image_endpoint", "regenerate_scene_image_endpoint"):
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "dispatch_generate_scene_image", dispatcher)

    return run_svc, dispatcher


@pytest.mark.asyncio
async def test_generate_scene_image_from_visual_plan_review(client, stub_single_scene_services):
    run_svc, dispatcher = stub_single_scene_services
    run_svc.runs[70] = _make_run(70, "VISUAL_PLAN_REVIEW")

    response = await client.post(
        "/api/creator/runs/70/visual-plan/scenes/scene-sec-0/generate-image",
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "test-img-task-id-789"
    assert body["run_id"] == 70
    assert body["scene_id"] == "scene-sec-0"
    assert body["current_stage"] == "VISUAL_PLAN_REVIEW"
    assert dispatcher.calls == [{
        "run_id": 70,
        "model_key": "sd15",
        "scene_id": "scene-sec-0",
        "prompt_override": None,
        "is_active": True,
    }]


@pytest.mark.asyncio
async def test_generate_scene_image_from_asset_review(client, stub_single_scene_services):
    """Generate-image is also allowed during VISUAL_ASSET_REVIEW (fill missing scenes)."""
    run_svc, dispatcher = stub_single_scene_services
    run_svc.runs[71] = _make_run(71, "VISUAL_ASSET_REVIEW")

    response = await client.post(
        "/api/creator/runs/71/visual-plan/scenes/scene-sec-1/generate-image",
    )

    assert response.status_code == 202
    assert dispatcher.calls[0]["scene_id"] == "scene-sec-1"
    assert dispatcher.calls[0]["is_active"] is True


@pytest.mark.asyncio
async def test_generate_scene_image_run_not_found(client, stub_single_scene_services):
    response = await client.post(
        "/api/creator/runs/999/visual-plan/scenes/scene-sec-0/generate-image",
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_generate_scene_image_wrong_stage(client, stub_single_scene_services):
    run_svc, dispatcher = stub_single_scene_services
    run_svc.runs[72] = _make_run(72, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/72/visual-plan/scenes/scene-sec-0/generate-image",
    )

    assert response.status_code == 400
    assert "SCRIPT_REVIEW" in response.json()["detail"]
    assert len(dispatcher.calls) == 0


@pytest.mark.asyncio
async def test_generate_scene_image_dispatch_failure(client, stub_single_scene_services):
    run_svc, _ = stub_single_scene_services
    run_svc.runs[73] = _make_run(73, "VISUAL_PLAN_REVIEW")

    def failing_dispatcher(run_id, model_key, scene_id, prompt_override, is_active):
        raise RuntimeError("Celery broker down")

    for route in runs_router.routes:
        if route.name == "generate_scene_image_endpoint":
            route.endpoint.__globals__["dispatch_generate_scene_image"] = failing_dispatcher

    response = await client.post(
        "/api/creator/runs/73/visual-plan/scenes/scene-sec-0/generate-image",
    )

    assert response.status_code == 503
    assert "enqueue" in response.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Single-scene regenerate-image tests (Issue #52)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_scene_image_success(client, stub_single_scene_services):
    run_svc, dispatcher = stub_single_scene_services
    run_svc.runs[80] = _make_run(80, "VISUAL_ASSET_REVIEW")

    response = await client.post(
        "/api/creator/runs/80/visual-plan/scenes/scene-sec-0/regenerate-image",
        json={"model_key": "sd15", "prompt_override": "A dark moody scene"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "test-img-task-id-789"
    assert body["run_id"] == 80
    assert body["scene_id"] == "scene-sec-0"
    assert body["current_stage"] == "VISUAL_ASSET_REVIEW"
    assert dispatcher.calls == [{
        "run_id": 80,
        "model_key": "sd15",
        "scene_id": "scene-sec-0",
        "prompt_override": "A dark moody scene",
        "is_active": False,  # regenerated assets are inactive
    }]


@pytest.mark.asyncio
async def test_regenerate_scene_image_default_model(client, stub_single_scene_services):
    run_svc, dispatcher = stub_single_scene_services
    run_svc.runs[81] = _make_run(81, "VISUAL_ASSET_REVIEW")

    response = await client.post(
        "/api/creator/runs/81/visual-plan/scenes/scene-sec-0/regenerate-image",
        json={},
    )

    assert response.status_code == 202
    assert dispatcher.calls[0]["model_key"] == "sd15"
    assert dispatcher.calls[0]["prompt_override"] is None
    assert dispatcher.calls[0]["is_active"] is False


@pytest.mark.asyncio
async def test_regenerate_scene_image_run_not_found(client, stub_single_scene_services):
    response = await client.post(
        "/api/creator/runs/999/visual-plan/scenes/scene-sec-0/regenerate-image",
        json={},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_regenerate_scene_image_wrong_stage(client, stub_single_scene_services):
    run_svc, dispatcher = stub_single_scene_services
    run_svc.runs[82] = _make_run(82, "VISUAL_PLAN_REVIEW")

    response = await client.post(
        "/api/creator/runs/82/visual-plan/scenes/scene-sec-0/regenerate-image",
        json={},
    )

    assert response.status_code == 400
    assert "VISUAL_PLAN_REVIEW" in response.json()["detail"]
    assert len(dispatcher.calls) == 0


@pytest.mark.asyncio
async def test_regenerate_scene_image_wrong_stage_script(client, stub_single_scene_services):
    run_svc, dispatcher = stub_single_scene_services
    run_svc.runs[83] = _make_run(83, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/83/visual-plan/scenes/scene-sec-0/regenerate-image",
        json={},
    )

    assert response.status_code == 400
    assert len(dispatcher.calls) == 0


@pytest.mark.asyncio
async def test_regenerate_scene_image_dispatch_failure(client, stub_single_scene_services):
    run_svc, _ = stub_single_scene_services
    run_svc.runs[84] = _make_run(84, "VISUAL_ASSET_REVIEW")

    def failing_dispatcher(run_id, model_key, scene_id, prompt_override, is_active):
        raise RuntimeError("Celery broker down")

    for route in runs_router.routes:
        if route.name == "regenerate_scene_image_endpoint":
            route.endpoint.__globals__["dispatch_generate_scene_image"] = failing_dispatcher

    response = await client.post(
        "/api/creator/runs/84/visual-plan/scenes/scene-sec-0/regenerate-image",
        json={"prompt_override": "New prompt"},
    )

    assert response.status_code == 503
    assert "enqueue" in response.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────────────
# Visual asset listing tests (Issue #53)
# ──────────────────────────────────────────────────────────────────────


class StubVisualAsset(BaseModel):
    id: int
    run_id: int
    scene_id: str
    version: int = 1
    asset_path: str
    prompt_snapshot: str | None = None
    model_used: str | None = None
    provider_type: str | None = None
    is_active: bool = True
    created_at: datetime


class StubVisualAssetService:
    def __init__(self) -> None:
        self.list_by_run_calls: list[int] = []
        self.list_by_scene_calls: list[dict[str, object]] = []
        self.select_active_calls: list[dict[str, object]] = []
        self._assets: dict[int, list[StubVisualAsset]] = {}  # run_id -> assets

    def add_asset(self, asset: StubVisualAsset) -> None:
        self._assets.setdefault(asset.run_id, []).append(asset)

    async def list_by_run(self, run_id: int) -> dict[str, list[StubVisualAsset]]:
        self.list_by_run_calls.append(run_id)
        assets = self._assets.get(run_id, [])
        grouped: dict[str, list[StubVisualAsset]] = {}
        for a in assets:
            grouped.setdefault(a.scene_id, []).append(a)
        return grouped

    async def list_by_scene(
        self, run_id: int, scene_id: str
    ) -> list[StubVisualAsset]:
        self.list_by_scene_calls.append({"run_id": run_id, "scene_id": scene_id})
        assets = self._assets.get(run_id, [])
        return sorted(
            [a for a in assets if a.scene_id == scene_id],
            key=lambda a: a.version,
            reverse=True,
        )

    async def select_active(
        self, run_id: int, scene_id: str, asset_id: int
    ) -> StubVisualAsset:
        self.select_active_calls.append({
            "run_id": run_id,
            "scene_id": scene_id,
            "asset_id": asset_id,
        })
        assets = self._assets.get(run_id, [])
        for a in assets:
            if a.id == asset_id:
                if a.scene_id != scene_id:
                    raise ValueError(
                        f"Asset {asset_id} does not belong to run {run_id} "
                        f"scene '{scene_id}'"
                    )
                return a.model_copy(update={"is_active": True})
        raise ValueError(f"Asset {asset_id} not found")


def _make_asset(
    asset_id: int,
    run_id: int,
    scene_id: str,
    version: int = 1,
    *,
    is_active: bool = True,
    prompt_snapshot: str | None = "A beautiful scene",
    model_used: str | None = "sd15",
    provider_type: str | None = "local-gpu",
) -> StubVisualAsset:
    return StubVisualAsset(
        id=asset_id,
        run_id=run_id,
        scene_id=scene_id,
        version=version,
        asset_path=f"data/artifacts/1/{run_id}/{scene_id}_v{version}.png",
        prompt_snapshot=prompt_snapshot,
        model_used=model_used,
        provider_type=provider_type,
        is_active=is_active,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def stub_listing_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubVisualAssetService]:
    run_svc = StubRunService()
    asset_svc = StubVisualAssetService()

    for route in runs_router.routes:
        if route.name in ("list_visual_assets_by_run", "list_visual_assets_by_scene"):
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "visual_asset_service", asset_svc)

    return run_svc, asset_svc


@pytest.mark.asyncio
async def test_list_visual_assets_by_run_success(client, stub_listing_services):
    run_svc, asset_svc = stub_listing_services
    run_svc.runs[90] = _make_run(90, "VISUAL_ASSET_REVIEW")

    asset_svc.add_asset(_make_asset(1, 90, "scene-0", 1, is_active=False))
    asset_svc.add_asset(_make_asset(2, 90, "scene-0", 2, is_active=True))
    asset_svc.add_asset(_make_asset(3, 90, "scene-1", 1, is_active=True))

    response = await client.get("/api/creator/runs/90/visual-assets")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 90
    assert body["total_scenes"] == 2
    assert body["total_assets"] == 3
    assert "scene-0" in body["scenes"]
    assert "scene-1" in body["scenes"]
    assert len(body["scenes"]["scene-0"]) == 2
    assert len(body["scenes"]["scene-1"]) == 1
    assert asset_svc.list_by_run_calls == [90]


@pytest.mark.asyncio
async def test_list_visual_assets_by_run_empty(client, stub_listing_services):
    run_svc, asset_svc = stub_listing_services
    run_svc.runs[91] = _make_run(91, "VISUAL_ASSET_REVIEW")

    response = await client.get("/api/creator/runs/91/visual-assets")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 91
    assert body["total_scenes"] == 0
    assert body["total_assets"] == 0
    assert body["scenes"] == {}


@pytest.mark.asyncio
async def test_list_visual_assets_by_run_not_found(client, stub_listing_services):
    response = await client.get("/api/creator/runs/999/visual-assets")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_visual_assets_by_run_includes_fields(client, stub_listing_services):
    """Verify asset serialization includes prompt_snapshot, model_used, provider_type, timestamps."""
    run_svc, asset_svc = stub_listing_services
    run_svc.runs[92] = _make_run(92, "VISUAL_ASSET_REVIEW")

    asset_svc.add_asset(_make_asset(
        10, 92, "scene-0", 1,
        prompt_snapshot="A serene landscape",
        model_used="sd15",
        provider_type="local-gpu",
    ))

    response = await client.get("/api/creator/runs/92/visual-assets")

    assert response.status_code == 200
    body = response.json()
    asset = body["scenes"]["scene-0"][0]
    assert asset["prompt_snapshot"] == "A serene landscape"
    assert asset["model_used"] == "sd15"
    assert asset["provider_type"] == "local-gpu"
    assert asset["is_active"] is True
    assert "created_at" in asset


@pytest.mark.asyncio
async def test_list_visual_assets_by_scene_success(client, stub_listing_services):
    run_svc, asset_svc = stub_listing_services
    run_svc.runs[93] = _make_run(93, "VISUAL_ASSET_REVIEW")

    asset_svc.add_asset(_make_asset(20, 93, "scene-sec-0", 1, is_active=False))
    asset_svc.add_asset(_make_asset(21, 93, "scene-sec-0", 2, is_active=True))
    asset_svc.add_asset(_make_asset(22, 93, "scene-sec-1", 1, is_active=True))  # different scene

    response = await client.get("/api/creator/runs/93/visual-assets/scene-sec-0")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 93
    assert body["scene_id"] == "scene-sec-0"
    assert body["total"] == 2
    # Newest first (version 2 before version 1)
    assert body["assets"][0]["version"] == 2
    assert body["assets"][1]["version"] == 1
    assert asset_svc.list_by_scene_calls == [{"run_id": 93, "scene_id": "scene-sec-0"}]


@pytest.mark.asyncio
async def test_list_visual_assets_by_scene_empty(client, stub_listing_services):
    """Empty list is valid — scene may not have any generated assets yet."""
    run_svc, asset_svc = stub_listing_services
    run_svc.runs[94] = _make_run(94, "VISUAL_ASSET_REVIEW")

    response = await client.get("/api/creator/runs/94/visual-assets/scene-sec-0")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["assets"] == []


@pytest.mark.asyncio
async def test_list_visual_assets_by_scene_not_found(client, stub_listing_services):
    response = await client.get("/api/creator/runs/999/visual-assets/scene-sec-0")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_visual_assets_by_scene_includes_fields(client, stub_listing_services):
    """Verify each asset in scene listing includes all expected fields."""
    run_svc, asset_svc = stub_listing_services
    run_svc.runs[95] = _make_run(95, "VISUAL_ASSET_REVIEW")

    asset_svc.add_asset(_make_asset(
        30, 95, "scene-sec-0", 1,
        prompt_snapshot="A dark forest",
        model_used="sd15",
        provider_type="local-gpu",
        is_active=True,
    ))

    response = await client.get("/api/creator/runs/95/visual-assets/scene-sec-0")

    assert response.status_code == 200
    asset = response.json()["assets"][0]
    assert asset["id"] == 30
    assert asset["run_id"] == 95
    assert asset["scene_id"] == "scene-sec-0"
    assert asset["version"] == 1
    assert asset["asset_path"] == "data/artifacts/1/95/scene-sec-0_v1.png"
    assert asset["prompt_snapshot"] == "A dark forest"
    assert asset["model_used"] == "sd15"
    assert asset["provider_type"] == "local-gpu"
    assert asset["is_active"] is True
    assert "created_at" in asset


# ──────────────────────────────────────────────────────────────────────
# Active visual asset selection tests (Issue #54)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def stub_select_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubVisualAssetService]:
    run_svc = StubRunService()
    asset_svc = StubVisualAssetService()

    for route in runs_router.routes:
        if route.name == "select_active_asset":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "visual_asset_service", asset_svc)

    return run_svc, asset_svc


@pytest.mark.asyncio
async def test_select_active_asset_success(client, stub_select_services):
    run_svc, asset_svc = stub_select_services
    run_svc.runs[100] = _make_run(100, "VISUAL_ASSET_REVIEW")

    asset_svc.add_asset(_make_asset(40, 100, "scene-0", 1, is_active=False))
    asset_svc.add_asset(_make_asset(41, 100, "scene-0", 2, is_active=True))

    response = await client.post(
        "/api/creator/runs/100/visual-assets/scene-0/select/40"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 40
    assert body["is_active"] is True
    assert body["scene_id"] == "scene-0"
    assert asset_svc.select_active_calls == [{"run_id": 100, "scene_id": "scene-0", "asset_id": 40}]


@pytest.mark.asyncio
async def test_select_active_asset_run_not_found(client, stub_select_services):
    response = await client.post(
        "/api/creator/runs/999/visual-assets/scene-0/select/1"
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_select_active_asset_wrong_stage(client, stub_select_services):
    run_svc, _ = stub_select_services
    run_svc.runs[101] = _make_run(101, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/101/visual-assets/scene-0/select/1"
    )
    assert response.status_code == 400
    assert "SCRIPT_REVIEW" in response.json()["detail"]


@pytest.mark.asyncio
async def test_select_active_asset_not_found(client, stub_select_services):
    run_svc, asset_svc = stub_select_services
    run_svc.runs[102] = _make_run(102, "VISUAL_ASSET_REVIEW")
    # No assets added — asset 999 doesn't exist

    response = await client.post(
        "/api/creator/runs/102/visual-assets/scene-0/select/999"
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_select_active_asset_wrong_scene(client, stub_select_services):
    run_svc, asset_svc = stub_select_services
    run_svc.runs[103] = _make_run(103, "VISUAL_ASSET_REVIEW")
    # Asset belongs to scene-1, not scene-0
    asset_svc.add_asset(_make_asset(50, 103, "scene-1", 1))

    response = await client.post(
        "/api/creator/runs/103/visual-assets/scene-0/select/50"
    )
    # Service raises ValueError for wrong scene — mapped to 400
    assert response.status_code == 400
    assert "does not belong" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_select_active_asset_during_generating(client, stub_select_services):
    """Selection is also allowed during VISUAL_ASSET_GENERATING stage."""
    run_svc, asset_svc = stub_select_services
    run_svc.runs[104] = _make_run(104, "VISUAL_ASSET_GENERATING")
    asset_svc.add_asset(_make_asset(60, 104, "scene-0", 1))

    response = await client.post(
        "/api/creator/runs/104/visual-assets/scene-0/select/60"
    )
    assert response.status_code == 200
    assert response.json()["id"] == 60


class StubAudioDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.task_id = "test-audio-task-id-abc"

    def __call__(self, run_id: int, tts_model: str, voice: str) -> str:
        self.calls.append({
            "run_id": run_id,
            "tts_model": tts_model,
            "voice": voice,
        })
        return self.task_id


@pytest.fixture
def stub_generate_audio_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubAudioDispatcher]:
    run_svc = StubRunService()
    dispatcher = StubAudioDispatcher()

    for route in runs_router.routes:
        if route.name == "generate_audio_trigger":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "dispatch_generate_audio", dispatcher)

    return run_svc, dispatcher


def _make_audio_run(run_id: int, stage: str = "VISUAL_ASSET_REVIEW") -> StubPipelineRun:
    """Helper to create a run in audio-relevant stage."""
    now = datetime.now(timezone.utc)
    return StubPipelineRun(
        id=run_id,
        project_id=1,
        current_stage=stage,
        status="running",
        review_stage=None,
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
async def test_generate_audio_from_visual_asset_review(client, stub_generate_audio_services):
    run_svc, dispatcher = stub_generate_audio_services
    run_svc.runs[110] = _make_audio_run(110, "VISUAL_ASSET_REVIEW")

    response = await client.post(
        "/api/creator/runs/110/generate-audio",
        json={"tts_model": "piper", "voice": "en_US-lessac-medium"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "test-audio-task-id-abc"
    assert body["run_id"] == 110
    assert body["current_stage"] == "AUDIO_GENERATING"
    # CAS was called for VISUAL_ASSET_REVIEW → AUDIO_GENERATING (no restart_from)
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 110
    assert cas_calls[0]["updates"] == {"current_stage": "AUDIO_GENERATING"}
    assert "VISUAL_ASSET_REVIEW" in cas_calls[0]["expected_stages"]
    assert dispatcher.calls == [{
        "run_id": 110,
        "tts_model": "piper",
        "voice": "en_US-lessac-medium",
    }]


@pytest.mark.asyncio
async def test_generate_audio_retry_from_generating(client, stub_generate_audio_services):
    run_svc, dispatcher = stub_generate_audio_services
    run_svc.runs[111] = _make_audio_run(111, "AUDIO_GENERATING")

    response = await client.post(
        "/api/creator/runs/111/generate-audio",
        json={"tts_model": "piper", "voice": "en_US-lessac-medium"},
    )

    assert response.status_code == 202
    # CAS was called for AUDIO_GENERATING → AUDIO_GENERATING with restart_from
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 111
    assert cas_calls[0]["updates"] == {
        "current_stage": "AUDIO_GENERATING",
        "restart_from": "AUDIO_GENERATING",
    }
    assert "AUDIO_GENERATING" in cas_calls[0]["expected_stages"]
    assert len(dispatcher.calls) == 1


@pytest.mark.asyncio
async def test_generate_audio_default_model(client, stub_generate_audio_services):
    run_svc, dispatcher = stub_generate_audio_services
    run_svc.runs[112] = _make_audio_run(112, "VISUAL_ASSET_REVIEW")

    response = await client.post(
        "/api/creator/runs/112/generate-audio",
        json={},
    )

    assert response.status_code == 202
    assert dispatcher.calls[0]["tts_model"] == "piper"
    assert dispatcher.calls[0]["voice"] == "en_US-lessac-medium"


@pytest.mark.asyncio
async def test_generate_audio_run_not_found(client, stub_generate_audio_services):
    _, _ = stub_generate_audio_services
    response = await client.post(
        "/api/creator/runs/999/generate-audio",
        json={},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_audio_wrong_stage(client, stub_generate_audio_services):
    run_svc, _ = stub_generate_audio_services
    run_svc.runs[113] = _make_audio_run(113, "IDEA_READY")

    response = await client.post(
        "/api/creator/runs/113/generate-audio",
        json={},
    )

    assert response.status_code == 400
    assert "IDEA_READY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_audio_wrong_stage_script_review(client, stub_generate_audio_services):
    run_svc, _ = stub_generate_audio_services
    run_svc.runs[114] = _make_audio_run(114, "SCRIPT_REVIEW")

    response = await client.post(
        "/api/creator/runs/114/generate-audio",
        json={},
    )

    assert response.status_code == 400
    assert "SCRIPT_REVIEW" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_audio_cas_conflict(client, stub_generate_audio_services):
    """CAS fails because stage changed between initial check and CAS."""
    run_svc, dispatcher = stub_generate_audio_services
    run_svc.runs[115] = _make_audio_run(115, "VISUAL_ASSET_REVIEW")

    async def cas_conflict(run_id, updates, expected_stages):
        return False, {"current_stage": "AUDIO_GENERATING", "id": run_id}

    run_svc.storage.conditional_update_run = cas_conflict

    response = await client.post(
        "/api/creator/runs/115/generate-audio",
        json={},
    )

    assert response.status_code == 409
    assert "conflict" in response.json()["detail"].lower()
    assert len(dispatcher.calls) == 0


@pytest.mark.asyncio
async def test_generate_audio_dispatch_failure_rollback(client, stub_generate_audio_services):
    """Celery dispatch failure triggers rollback to original stage."""
    run_svc, _ = stub_generate_audio_services
    run_svc.runs[116] = _make_audio_run(116, "VISUAL_ASSET_REVIEW")

    def failing_dispatcher(run_id, tts_model, voice):
        raise RuntimeError("Celery broker down")

    from shorts_api.main import runs_router as _r
    for route in _r.routes:
        if route.name == "generate_audio_trigger":
            route.endpoint.__globals__["dispatch_generate_audio"] = failing_dispatcher

    response = await client.post(
        "/api/creator/runs/116/generate-audio",
        json={},
    )

    assert response.status_code == 503
    assert "enqueue" in response.json()["detail"].lower()

    # Rollback: CAS was called twice — first to advance, then to rollback
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 2
    # Second CAS = rollback to VISUAL_ASSET_REVIEW
    rollback = cas_calls[1]
    assert rollback["updates"]["current_stage"] == "VISUAL_ASSET_REVIEW"
    assert rollback["expected_stages"] == frozenset({"AUDIO_GENERATING"})

    # Verify run was actually rolled back to VISUAL_ASSET_REVIEW
    assert run_svc.runs[116].current_stage == "VISUAL_ASSET_REVIEW"



# ──────────────────────────────────────────────────────────────────────
# POST /runs/{run_id}/generate-subtitles
# ──────────────────────────────────────────────────────────────────────


class StubSubtitleDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.task_id = "test-subtitle-task-id-xyz"

    def __call__(self, run_id: int, subtitle_model: str, subtitle_format: str) -> str:
        self.calls.append({
            "run_id": run_id,
            "subtitle_model": subtitle_model,
            "subtitle_format": subtitle_format,
        })
        return self.task_id


@pytest.fixture
def stub_generate_subtitles_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubSubtitleDispatcher]:
    run_svc = StubRunService()
    dispatcher = StubSubtitleDispatcher()

    for route in runs_router.routes:
        if route.name == "generate_subtitles_trigger":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "dispatch_generate_subtitles", dispatcher)

    return run_svc, dispatcher


def _make_subtitle_run(run_id: int, stage: str = "AUDIO_GENERATING") -> StubPipelineRun:
    """Helper to create a run in subtitle-relevant stage."""
    now = datetime.now(timezone.utc)
    return StubPipelineRun(
        id=run_id,
        project_id=1,
        current_stage=stage,
        status="running",
        review_stage=None,
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
async def test_generate_subtitles_from_audio_generating(client, stub_generate_subtitles_services):
    run_svc, dispatcher = stub_generate_subtitles_services
    run_svc.runs[120] = _make_subtitle_run(120, "AUDIO_GENERATING")

    response = await client.post(
        "/api/creator/runs/120/generate-subtitles",
        json={"subtitle_model": "whisper-tiny", "subtitle_format": "srt"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "test-subtitle-task-id-xyz"
    assert body["run_id"] == 120
    assert body["current_stage"] == "SUBTITLE_GENERATING"
    # CAS was called for AUDIO_GENERATING → SUBTITLE_GENERATING (no restart_from)
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 120
    assert cas_calls[0]["updates"] == {"current_stage": "SUBTITLE_GENERATING"}
    assert "AUDIO_GENERATING" in cas_calls[0]["expected_stages"]
    assert dispatcher.calls == [{
        "run_id": 120,
        "subtitle_model": "whisper-tiny",
        "subtitle_format": "srt",
    }]


@pytest.mark.asyncio
async def test_generate_subtitles_retry_from_generating(client, stub_generate_subtitles_services):
    run_svc, dispatcher = stub_generate_subtitles_services
    run_svc.runs[121] = _make_subtitle_run(121, "SUBTITLE_GENERATING")

    response = await client.post(
        "/api/creator/runs/121/generate-subtitles",
        json={"subtitle_model": "whisper-tiny", "subtitle_format": "srt"},
    )

    assert response.status_code == 202
    # CAS was called for SUBTITLE_GENERATING → SUBTITLE_GENERATING with restart_from
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 121
    assert cas_calls[0]["updates"] == {
        "current_stage": "SUBTITLE_GENERATING",
        "restart_from": "SUBTITLE_GENERATING",
    }
    assert "SUBTITLE_GENERATING" in cas_calls[0]["expected_stages"]
    assert len(dispatcher.calls) == 1


@pytest.mark.asyncio
async def test_generate_subtitles_default_model(client, stub_generate_subtitles_services):
    run_svc, dispatcher = stub_generate_subtitles_services
    run_svc.runs[122] = _make_subtitle_run(122, "AUDIO_GENERATING")

    response = await client.post(
        "/api/creator/runs/122/generate-subtitles",
        json={},
    )

    assert response.status_code == 202
    assert dispatcher.calls[0]["subtitle_model"] == "whisper-tiny"
    assert dispatcher.calls[0]["subtitle_format"] == "srt"


@pytest.mark.asyncio
async def test_generate_subtitles_run_not_found(client, stub_generate_subtitles_services):
    _, _ = stub_generate_subtitles_services
    response = await client.post(
        "/api/creator/runs/999/generate-subtitles",
        json={},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_subtitles_wrong_stage(client, stub_generate_subtitles_services):
    run_svc, _ = stub_generate_subtitles_services
    run_svc.runs[123] = _make_subtitle_run(123, "IDEA_READY")

    response = await client.post(
        "/api/creator/runs/123/generate-subtitles",
        json={},
    )

    assert response.status_code == 400
    assert "IDEA_READY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_subtitles_wrong_stage_visual(client, stub_generate_subtitles_services):
    run_svc, _ = stub_generate_subtitles_services
    run_svc.runs[124] = _make_subtitle_run(124, "VISUAL_ASSET_REVIEW")

    response = await client.post(
        "/api/creator/runs/124/generate-subtitles",
        json={},
    )

    assert response.status_code == 400
    assert "VISUAL_ASSET_REVIEW" in response.json()["detail"]


@pytest.mark.asyncio
async def test_generate_subtitles_cas_conflict(client, stub_generate_subtitles_services):
    """CAS fails because stage changed between initial check and CAS."""
    run_svc, dispatcher = stub_generate_subtitles_services
    run_svc.runs[125] = _make_subtitle_run(125, "AUDIO_GENERATING")

    async def cas_conflict(run_id, updates, expected_stages):
        return False, {"current_stage": "SUBTITLE_GENERATING", "id": run_id}

    run_svc.storage.conditional_update_run = cas_conflict

    response = await client.post(
        "/api/creator/runs/125/generate-subtitles",
        json={},
    )

    assert response.status_code == 409
    assert "conflict" in response.json()["detail"].lower()
    assert len(dispatcher.calls) == 0


@pytest.mark.asyncio
async def test_generate_subtitles_dispatch_failure_rollback(client, stub_generate_subtitles_services):
    """Celery dispatch failure triggers rollback to original stage."""
    run_svc, _ = stub_generate_subtitles_services
    run_svc.runs[126] = _make_subtitle_run(126, "AUDIO_GENERATING")

    def failing_dispatcher(run_id, subtitle_model, subtitle_format):
        raise RuntimeError("Celery broker down")

    from shorts_api.main import runs_router as _r
    for route in _r.routes:
        if route.name == "generate_subtitles_trigger":
            route.endpoint.__globals__["dispatch_generate_subtitles"] = failing_dispatcher

    response = await client.post(
        "/api/creator/runs/126/generate-subtitles",
        json={},
    )

    assert response.status_code == 503
    assert "enqueue" in response.json()["detail"].lower()

    # Rollback: CAS was called twice — first to advance, then to rollback
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 2
    # Second CAS = rollback to AUDIO_GENERATING
    rollback = cas_calls[1]
    assert rollback["updates"]["current_stage"] == "AUDIO_GENERATING"
    assert rollback["expected_stages"] == frozenset({"SUBTITLE_GENERATING"})

    # Verify run was actually rolled back to AUDIO_GENERATING
    assert run_svc.runs[126].current_stage == "AUDIO_GENERATING"


# ── Render endpoint tests ──────────────────────────────────────────


class StubRenderDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.task_id = "test-render-task-id-xyz"

    def __call__(self, run_id: int, render_profile: str) -> str:
        self.calls.append({
            "run_id": run_id,
            "render_profile": render_profile,
        })
        return self.task_id


@pytest.fixture
def stub_generate_render_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubRenderDispatcher]:
    run_svc = StubRunService()
    dispatcher = StubRenderDispatcher()

    for route in runs_router.routes:
        if route.name == "render_trigger":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "dispatch_render_video", dispatcher)

    return run_svc, dispatcher


def _make_render_run(run_id: int, stage: str = "SUBTITLE_GENERATING") -> StubPipelineRun:
    """Helper to create a run in render-relevant stage."""
    now = datetime.now(timezone.utc)
    return StubPipelineRun(
        id=run_id,
        project_id=1,
        current_stage=stage,
        status="running",
        review_stage=None,
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
async def test_render_from_subtitle_generating(client, stub_generate_render_services):
    run_svc, dispatcher = stub_generate_render_services
    run_svc.runs[130] = _make_render_run(130, "SUBTITLE_GENERATING")

    response = await client.post(
        "/api/creator/runs/130/render",
        json={"render_profile": "high_quality"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "test-render-task-id-xyz"
    assert body["run_id"] == 130
    assert body["current_stage"] == "RENDER_GENERATING"
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["run_id"] == 130
    assert cas_calls[0]["updates"] == {"current_stage": "RENDER_GENERATING"}
    assert "SUBTITLE_GENERATING" in cas_calls[0]["expected_stages"]
    assert dispatcher.calls == [{
        "run_id": 130,
        "render_profile": "high_quality",
    }]


@pytest.mark.asyncio
async def test_render_retry_from_generating(client, stub_generate_render_services):
    run_svc, dispatcher = stub_generate_render_services
    run_svc.runs[131] = _make_render_run(131, "RENDER_GENERATING")

    response = await client.post(
        "/api/creator/runs/131/render",
        json={"render_profile": "shorts_default"},
    )

    assert response.status_code == 202
    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 1
    assert cas_calls[0]["updates"] == {
        "current_stage": "RENDER_GENERATING",
        "restart_from": "RENDER_GENERATING",
    }
    assert "RENDER_GENERATING" in cas_calls[0]["expected_stages"]
    assert len(dispatcher.calls) == 1


@pytest.mark.asyncio
async def test_render_default_profile(client, stub_generate_render_services):
    run_svc, dispatcher = stub_generate_render_services
    run_svc.runs[132] = _make_render_run(132, "SUBTITLE_GENERATING")

    response = await client.post(
        "/api/creator/runs/132/render",
        json={},
    )

    assert response.status_code == 202
    assert dispatcher.calls[0]["render_profile"] == "shorts_default"


@pytest.mark.asyncio
async def test_render_run_not_found(client, stub_generate_render_services):
    _, _ = stub_generate_render_services
    response = await client.post(
        "/api/creator/runs/999/render",
        json={},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_render_wrong_stage(client, stub_generate_render_services):
    run_svc, _ = stub_generate_render_services
    run_svc.runs[133] = _make_render_run(133, "IDEA_READY")

    response = await client.post(
        "/api/creator/runs/133/render",
        json={},
    )

    assert response.status_code == 400
    assert "IDEA_READY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_render_cas_conflict(client, stub_generate_render_services):
    run_svc, dispatcher = stub_generate_render_services
    run_svc.runs[134] = _make_render_run(134, "SUBTITLE_GENERATING")

    async def cas_conflict(run_id, updates, expected_stages):
        return False, {"current_stage": "RENDER_GENERATING", "id": run_id}

    run_svc.storage.conditional_update_run = cas_conflict

    response = await client.post(
        "/api/creator/runs/134/render",
        json={},
    )

    assert response.status_code == 409
    assert "conflict" in response.json()["detail"].lower()
    assert len(dispatcher.calls) == 0


@pytest.mark.asyncio
async def test_render_dispatch_failure_rollback(client, stub_generate_render_services):
    run_svc, _ = stub_generate_render_services
    run_svc.runs[135] = _make_render_run(135, "SUBTITLE_GENERATING")

    def failing_dispatcher(run_id, render_profile):
        raise RuntimeError("Celery broker down")

    from shorts_api.main import runs_router as _r
    for route in _r.routes:
        if route.name == "render_trigger":
            route.endpoint.__globals__["dispatch_render_video"] = failing_dispatcher

    response = await client.post(
        "/api/creator/runs/135/render",
        json={},
    )

    assert response.status_code == 503
    assert "enqueue" in response.json()["detail"].lower()

    cas_calls = run_svc.storage.conditional_update_calls
    assert len(cas_calls) == 2
    rollback = cas_calls[1]
    assert rollback["updates"]["current_stage"] == "SUBTITLE_GENERATING"
    assert rollback["expected_stages"] == frozenset({"RENDER_GENERATING"})

    assert run_svc.runs[135].current_stage == "SUBTITLE_GENERATING"


# ── Preview endpoint tests ────────────────────────────────────────


class StubVideoArtifact:
    def __init__(self, id: int, path: str, render_profile: str | None, created_at: datetime) -> None:
        self.id = id
        self.path = path
        self.render_profile = render_profile
        self.created_at = created_at


class StubAudioArtifact:
    def __init__(self, id: int, path: str, model_used: str, created_at: datetime) -> None:
        self.id = id
        self.path = path
        self.model_used = model_used
        self.created_at = created_at


class StubSubtitleArtifact:
    def __init__(self, id: int, path: str, fmt: str, created_at: datetime) -> None:
        self.id = id
        self.path = path
        self.format = fmt
        self.created_at = created_at


class StubPreviewRenderService:
    def __init__(self, artifact: StubVideoArtifact | None = None) -> None:
        self.artifact = artifact

    async def get_latest(self, run_id: int) -> StubVideoArtifact | None:
        return self.artifact


class StubPreviewAudioService:
    def __init__(self, artifact: StubAudioArtifact | None = None) -> None:
        self.artifact = artifact

    async def get_latest(self, run_id: int) -> StubAudioArtifact | None:
        return self.artifact


class StubPreviewSubtitleService:
    def __init__(self, artifact: StubSubtitleArtifact | None = None) -> None:
        self.artifact = artifact

    async def get_latest(self, run_id: int) -> StubSubtitleArtifact | None:
        return self.artifact


@pytest.fixture
def stub_preview_services(monkeypatch: pytest.MonkeyPatch):
    now = datetime.now(timezone.utc)
    run_svc = StubRunService()
    render_svc = StubPreviewRenderService(
        StubVideoArtifact(1, "data/artifacts/200/render/output.mp4", "shorts_default", now)
    )
    audio_svc = StubPreviewAudioService(
        StubAudioArtifact(2, "data/artifacts/200/audio/audio.wav", "piper", now)
    )
    subtitle_svc = StubPreviewSubtitleService(
        StubSubtitleArtifact(3, "data/artifacts/200/subtitles/subtitles.srt", "srt", now)
    )

    for route in runs_router.routes:
        if route.name == "get_preview":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "render_service", render_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "audio_service", audio_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "subtitle_service", subtitle_svc)

    return run_svc, render_svc, audio_svc, subtitle_svc


def _make_preview_run(run_id: int, stage: str = "FINAL_REVIEW") -> StubPipelineRun:
    now = datetime.now(timezone.utc)
    return StubPipelineRun(
        id=run_id,
        project_id=1,
        current_stage=stage,
        status="running",
        review_stage=None,
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
async def test_preview_full_artifacts(client, stub_preview_services):
    run_svc, _, _, _ = stub_preview_services
    run_svc.runs[200] = _make_preview_run(200, "FINAL_REVIEW")

    response = await client.get("/api/creator/runs/200/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 200
    assert body["current_stage"] == "FINAL_REVIEW"
    assert body["video"]["id"] == 1
    assert body["video"]["path"] == "data/artifacts/200/render/output.mp4"
    assert body["video"]["render_profile"] == "shorts_default"
    assert body["audio"]["id"] == 2
    assert body["audio"]["model_used"] == "piper"
    assert body["subtitle"]["id"] == 3
    assert body["subtitle"]["format"] == "srt"


@pytest.mark.asyncio
async def test_preview_no_artifacts(client, stub_preview_services):
    run_svc, render_svc, audio_svc, subtitle_svc = stub_preview_services
    render_svc.artifact = None
    audio_svc.artifact = None
    subtitle_svc.artifact = None
    run_svc.runs[201] = _make_preview_run(201, "RENDER_GENERATING")

    response = await client.get("/api/creator/runs/201/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["video"] is None
    assert body["audio"] is None
    assert body["subtitle"] is None


@pytest.mark.asyncio
async def test_preview_run_not_found(client, stub_preview_services):
    _, _, _, _ = stub_preview_services
    response = await client.get("/api/creator/runs/999/preview")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()