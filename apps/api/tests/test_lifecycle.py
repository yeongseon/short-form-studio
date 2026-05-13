# pyright: reportMissingImports=false

from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from typing import Literal

import pytest
import shorts_api.routes.creator_runs_utils as creator_runs_utils
from fastapi.routing import APIRoute
from pydantic import BaseModel
from shorts_api.main import projects_router, runs_router


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


class StubProject(BaseModel):
    id: int
    title: str = "Project"
    created_at: datetime
    updated_at: datetime


class StubRunService:
    def __init__(self) -> None:
        self.runs: dict[int, StubPipelineRun] = {}
        self.get_run_calls: list[int] = []
        self.stop_run_calls: list[int] = []
        self.resume_run_calls: list[int] = []
        self.go_back_calls: list[int] = []
        self.update_model_defaults_calls: list[dict[str, object]] = []
        self.delete_run_calls: list[int] = []
        self.list_runs_by_project_calls: list[int] = []
        self.resume_errors: dict[int, Exception] = {}
        self.go_back_errors: dict[int, Exception] = {}
        self.update_model_defaults_errors: dict[int, Exception] = {}

    async def get_run(self, run_id: int) -> StubPipelineRun | None:
        self.get_run_calls.append(run_id)
        return self.runs.get(run_id)

    async def stop_run(self, run_id: int) -> StubPipelineRun:
        self.stop_run_calls.append(run_id)
        run = self.runs.get(run_id)
        if run is None:
            raise ValueError("Run not found")
        updated = run.model_copy(update={"status": "cancelled"})
        self.runs[run_id] = updated
        return updated

    async def resume_run(self, run_id: int) -> StubPipelineRun:
        self.resume_run_calls.append(run_id)
        error = self.resume_errors.get(run_id)
        if error is not None:
            raise error
        run = self.runs.get(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        updated = run.model_copy(update={"status": "running"})
        self.runs[run_id] = updated
        return updated

    async def go_back(self, run_id: int) -> StubPipelineRun:
        self.go_back_calls.append(run_id)
        error = self.go_back_errors.get(run_id)
        if error is not None:
            raise error
        run = self.runs.get(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        updated = run.model_copy(update={"current_stage": "SCRIPT_GENERATING"})
        self.runs[run_id] = updated
        return updated

    async def update_model_defaults(self, run_id: int, updates: dict[str, str]) -> StubPipelineRun:
        self.update_model_defaults_calls.append({"run_id": run_id, "updates": updates})
        error = self.update_model_defaults_errors.get(run_id)
        if error is not None:
            raise error
        run = self.runs.get(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        merged = dict(run.model_defaults or {})
        merged.update(updates)
        updated = run.model_copy(update={"model_defaults": merged})
        self.runs[run_id] = updated
        return updated

    async def delete_run(self, run_id: int) -> bool:
        self.delete_run_calls.append(run_id)
        return self.runs.pop(run_id, None) is not None

    async def list_runs_by_project(self, project_id: int) -> list[StubPipelineRun]:
        self.list_runs_by_project_calls.append(project_id)
        return sorted(
            [run for run in self.runs.values() if run.project_id == project_id],
            key=lambda run: run.id,
            reverse=True,
        )


class StubProjectService:
    def __init__(self) -> None:
        self.projects: dict[int, StubProject] = {}
        self.delete_project_calls: list[int] = []

    async def delete_project(self, project_id: int) -> bool:
        self.delete_project_calls.append(project_id)
        return self.projects.pop(project_id, None) is not None


class StubRevokeTasks:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def __call__(self, run_id: int) -> None:
        self.calls.append(run_id)


class StubArtifactLifecycleService:
    def __init__(self) -> None:
        self.delete_artifacts_for_run_calls: list[int] = []

    async def delete_artifacts_for_run(self, run_id: int) -> None:
        self.delete_artifacts_for_run_calls.append(run_id)


def _iter_api_routes(routes: Sequence[object]) -> list[APIRoute]:
    return [route for route in routes if isinstance(route, APIRoute)]


@pytest.fixture
def stub_lifecycle_services(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[
    tuple[StubRunService, StubProjectService, StubRevokeTasks, StubArtifactLifecycleService]
]:
    from shorts_api.auth import CurrentUser, require_run_access, require_project_access
    from shorts_api.main import app

    run_svc = StubRunService()
    project_svc = StubProjectService()
    revoke_tasks = StubRevokeTasks()
    artifact_lifecycle_svc = StubArtifactLifecycleService()

    for route in _iter_api_routes(runs_router.routes):
        if route.name in {
            "stop_run",
            "resume_run",
            "go_back",
            "update_model_defaults",
            "delete_run",
        }:
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(
                route.endpoint.__globals__, "_revoke_active_tasks_for_run", revoke_tasks
            )
            monkeypatch.setitem(
                route.endpoint.__globals__, "artifact_download_service", artifact_lifecycle_svc
            )

    for route in _iter_api_routes(projects_router.routes):
        if route.name == "delete_project":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", project_svc)
            monkeypatch.setitem(
                route.endpoint.__globals__, "artifact_download_service", artifact_lifecycle_svc
            )

    monkeypatch.setattr(creator_runs_utils, "_revoke_active_tasks_for_run", revoke_tasks)

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, StubPipelineRun]:
        run = run_svc.runs.get(run_id)
        if run is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Run not found")
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    async def _require_project_access(project_id: int) -> tuple[CurrentUser, StubProject]:
        project = project_svc.projects.get(project_id)
        if project is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Project not found")
        return CurrentUser(user_id=1, workspace_id=1), project

    app.dependency_overrides[require_project_access] = _require_project_access

    yield run_svc, project_svc, revoke_tasks, artifact_lifecycle_svc

    app.dependency_overrides.pop(require_run_access, None)
    app.dependency_overrides.pop(require_project_access, None)


def _make_run(
    run_id: int,
    *,
    project_id: int = 1,
    status: Literal["pending", "running", "paused", "completed", "failed", "cancelled"] = "running",
    stage: str = "SCRIPT_GENERATING",
    model_defaults: dict[str, str] | None = None,
) -> StubPipelineRun:
    now = datetime.now(timezone.utc)
    return StubPipelineRun(
        id=run_id,
        project_id=project_id,
        current_stage=stage,
        status=status,
        review_stage=None,
        restart_from=None,
        model_defaults=model_defaults,
        metadata=None,
        style_preset="default",
        started_at=now,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )


def _make_project(project_id: int) -> StubProject:
    now = datetime.now(timezone.utc)
    return StubProject(id=project_id, created_at=now, updated_at=now)


@pytest.mark.asyncio
async def test_stop_run_success(client, stub_lifecycle_services):
    run_svc, _, revoke_tasks, _ = stub_lifecycle_services
    run_svc.runs[10] = _make_run(10)

    response = await client.post("/api/creator/runs/10/stop")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert revoke_tasks.calls == [10]
    assert run_svc.stop_run_calls == [10]


@pytest.mark.asyncio
async def test_stop_run_not_found(client, stub_lifecycle_services):
    run_svc, _, revoke_tasks, _ = stub_lifecycle_services

    response = await client.post("/api/creator/runs/404/stop")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}
    assert run_svc.stop_run_calls == []
    assert revoke_tasks.calls == []


@pytest.mark.asyncio
async def test_resume_run_success(client, stub_lifecycle_services):
    run_svc, _, _, _ = stub_lifecycle_services
    run_svc.runs[11] = _make_run(11, status="cancelled", stage="SCRIPT_REVIEW")

    response = await client.post("/api/creator/runs/11/resume")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert run_svc.resume_run_calls == [11]


@pytest.mark.asyncio
async def test_resume_run_not_found(client, stub_lifecycle_services):
    run_svc, _, _, _ = stub_lifecycle_services
    run_svc.resume_errors[999] = ValueError("Run 999 not found")

    response = await client.post("/api/creator/runs/999/resume")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


@pytest.mark.asyncio
async def test_resume_run_wrong_state(client, stub_lifecycle_services):
    run_svc, _, _, _ = stub_lifecycle_services
    run_svc.runs[12] = _make_run(12)
    run_svc.resume_errors[12] = ValueError(
        "Run 12 has status 'running', can only resume cancelled or failed runs"
    )

    response = await client.post("/api/creator/runs/12/resume")

    assert response.status_code == 400
    assert "can only resume" in response.json()["detail"]


@pytest.mark.asyncio
async def test_go_back_success(client, stub_lifecycle_services):
    run_svc, _, _, _ = stub_lifecycle_services
    run_svc.runs[13] = _make_run(13, stage="SCRIPT_REVIEW")

    response = await client.post("/api/creator/runs/13/go-back")

    assert response.status_code == 200
    assert response.json()["current_stage"] == "SCRIPT_GENERATING"
    assert run_svc.go_back_calls == [13]


@pytest.mark.asyncio
async def test_go_back_not_found(client, stub_lifecycle_services):
    run_svc, _, _, _ = stub_lifecycle_services
    run_svc.go_back_errors[888] = ValueError("Run 888 not found")

    response = await client.post("/api/creator/runs/888/go-back")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


@pytest.mark.asyncio
async def test_go_back_invalid_state_returns_400(client, stub_lifecycle_services):
    run_svc, _, _, _ = stub_lifecycle_services
    run_svc.runs[14] = _make_run(14)
    run_svc.go_back_errors[14] = ValueError("Cannot go back from stage 'IDEA_READY'")

    response = await client.post("/api/creator/runs/14/go-back")

    assert response.status_code == 400
    assert "Cannot go back" in response.json()["detail"]


@pytest.mark.asyncio
async def test_go_back_stage_conflict_returns_409(client, stub_lifecycle_services):
    run_svc, _, _, _ = stub_lifecycle_services
    run_svc.runs[15] = _make_run(15)
    run_svc.go_back_errors[15] = RuntimeError(
        "Stage conflict: expected 'SCRIPT_REVIEW' but run is at 'VISUAL_PLAN_SETUP'"
    )

    response = await client.post("/api/creator/runs/15/go-back")

    assert response.status_code == 409
    assert "Stage conflict" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_model_defaults_success(client, stub_lifecycle_services):
    run_svc, _, _, _ = stub_lifecycle_services
    run_svc.runs[16] = _make_run(16, model_defaults={"script_model": "qwen3-4b"})

    response = await client.patch(
        "/api/creator/runs/16/model-defaults",
        json={"image_model": "sd15"},
    )

    assert response.status_code == 200
    assert response.json()["model_defaults"] == {
        "script_model": "qwen3-4b",
        "image_model": "sd15",
    }
    assert run_svc.update_model_defaults_calls == [
        {"run_id": 16, "updates": {"image_model": "sd15"}}
    ]


@pytest.mark.asyncio
async def test_update_model_defaults_not_found(client, stub_lifecycle_services):
    run_svc, _, _, _ = stub_lifecycle_services
    run_svc.update_model_defaults_errors[404] = ValueError("Run 404 not found")

    response = await client.patch(
        "/api/creator/runs/404/model-defaults",
        json={"script_model": "qwen3-4b"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


@pytest.mark.asyncio
async def test_update_model_defaults_empty_body_returns_400(client, stub_lifecycle_services):
    run_svc, _, _, _ = stub_lifecycle_services

    run_svc.runs[16] = _make_run(16)

    response = await client.patch(
        "/api/creator/runs/16/model-defaults",
        json={},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "No model defaults to update"}
    assert run_svc.update_model_defaults_calls == []


@pytest.mark.asyncio
async def test_delete_run_success_with_artifact_cleanup(client, stub_lifecycle_services):
    run_svc, _, revoke_tasks, artifact_lifecycle_svc = stub_lifecycle_services
    run_svc.runs[17] = _make_run(17)

    response = await client.delete("/api/creator/runs/17")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "run_id": 17}
    assert revoke_tasks.calls == [17]
    assert artifact_lifecycle_svc.delete_artifacts_for_run_calls == [17]
    assert run_svc.delete_run_calls == [17]


@pytest.mark.asyncio
async def test_delete_run_not_found_when_missing_before_delete(client, stub_lifecycle_services):
    run_svc, _, revoke_tasks, artifact_lifecycle_svc = stub_lifecycle_services

    response = await client.delete("/api/creator/runs/700")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}
    assert run_svc.delete_run_calls == []
    assert artifact_lifecycle_svc.delete_artifacts_for_run_calls == []
    assert revoke_tasks.calls == []


@pytest.mark.asyncio
async def test_delete_project_success_cascades_run_cleanup(client, stub_lifecycle_services):
    run_svc, project_svc, revoke_tasks, artifact_lifecycle_svc = stub_lifecycle_services
    project_svc.projects[31] = _make_project(31)
    run_svc.runs[41] = _make_run(41, project_id=31)
    run_svc.runs[42] = _make_run(42, project_id=31)

    response = await client.delete("/api/creator/projects/31")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "project_id": 31}
    assert run_svc.list_runs_by_project_calls == [31]
    assert project_svc.delete_project_calls == [31]
    assert revoke_tasks.calls == [42, 41]
    assert artifact_lifecycle_svc.delete_artifacts_for_run_calls == [42, 41]


@pytest.mark.asyncio
async def test_delete_project_not_found(client, stub_lifecycle_services):
    run_svc, project_svc, revoke_tasks, artifact_lifecycle_svc = stub_lifecycle_services

    response = await client.delete("/api/creator/projects/404")

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}
    assert run_svc.list_runs_by_project_calls == []
    assert project_svc.delete_project_calls == []
    assert artifact_lifecycle_svc.delete_artifacts_for_run_calls == []
    assert revoke_tasks.calls == []
