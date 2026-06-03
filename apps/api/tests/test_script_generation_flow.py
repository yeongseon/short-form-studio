# pyright: reportMissingImports=false

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime, timezone

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel
from shorts_api.auth import CurrentUser, require_project_access, require_run_access
from shorts_api.main import app


def _iter_api_routes(routes: Sequence[object]) -> list[APIRoute]:
    return [route for route in routes if isinstance(route, APIRoute)]


class StubProject(BaseModel):
    id: int
    title: str
    source_type: str
    idea_brief: str | None = None
    markdown_source: str | None = None
    json_script: str | None = None
    url_source: str | None = None
    status: str = "draft"
    workspace_id: int = 1
    created_at: datetime
    updated_at: datetime


class StubRun(BaseModel):
    id: int
    project_id: int
    current_stage: str
    status: str = "running"
    restart_from: str | None = None
    review_stage: str | None = None
    created_at: datetime
    updated_at: datetime


class StubDraft(BaseModel):
    id: int
    run_id: int
    source_type: str
    markdown_content: str | None = None
    structured_script: list[object] | None = None
    version: int
    created_at: datetime


class StubProjectService:
    def __init__(self) -> None:
        self.projects: dict[int, StubProject] = {}
        self.next_id = 1

    async def create_project(
        self,
        title: str,
        source_type: str,
        idea_brief: str | None = None,
        markdown_source: str | None = None,
        json_script: str | None = None,
        url_source: str | None = None,
        workspace_id: int = 1,
    ) -> StubProject:
        now = datetime.now(timezone.utc)
        project = StubProject(
            id=self.next_id,
            title=title,
            source_type=source_type,
            idea_brief=idea_brief,
            markdown_source=markdown_source,
            json_script=json_script,
            url_source=url_source,
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
        )
        self.projects[project.id] = project
        self.next_id += 1
        return project

    async def get_project(
        self, project_id: int, workspace_id: int | None = None
    ) -> StubProject | None:
        return self.projects.get(project_id)


class StubRunStorage:
    def __init__(self, run_service: "StubRunService") -> None:
        self.run_service = run_service

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, object],
        expected_stages: frozenset[str],
        workspace_id: int | None = None,
    ) -> tuple[bool, dict[str, object] | None]:
        _ = workspace_id
        run = self.run_service.runs.get(run_id)
        if run is None:
            return False, None
        if run.current_stage not in expected_stages:
            return False, run.model_dump(mode="json")
        updated = run.model_copy(update=updates)
        self.run_service.runs[run_id] = updated
        return True, updated.model_dump(mode="json")


class StubRunService:
    def __init__(self) -> None:
        self.runs: dict[int, StubRun] = {}
        self.next_id = 1
        self.storage = StubRunStorage(self)

    async def create_run(
        self,
        project_id: int,
        model_defaults: dict[str, str] | None,
        style_preset: str,
        metadata: dict[str, object] | None,
        workspace_id: int | None = None,
    ) -> StubRun:
        _ = model_defaults, style_preset, metadata, workspace_id
        now = datetime.now(timezone.utc)
        run = StubRun(
            id=self.next_id,
            project_id=project_id,
            current_stage="IDEA_READY",
            status="running",
            created_at=now,
            updated_at=now,
        )
        self.runs[run.id] = run
        self.next_id += 1
        return run

    async def get_run(self, run_id: int, workspace_id: int | None = None) -> StubRun | None:
        _ = workspace_id
        return self.runs.get(run_id)


class StubScriptService:
    def __init__(self) -> None:
        self.drafts: dict[int, list[StubDraft]] = {}
        self.next_id = 1

    async def save_draft(
        self,
        run_id: int,
        source_type: str,
        markdown_content: str | None = None,
        structured_script: list[object] | None = None,
    ) -> StubDraft:
        versions = self.drafts.setdefault(run_id, [])
        draft = StubDraft(
            id=self.next_id,
            run_id=run_id,
            source_type=source_type,
            markdown_content=markdown_content,
            structured_script=structured_script,
            version=len(versions) + 1,
            created_at=datetime.now(timezone.utc),
        )
        self.next_id += 1
        versions.append(draft)
        return draft

    async def get_active_draft(self, run_id: int) -> StubDraft | None:
        versions = self.drafts.get(run_id, [])
        if not versions:
            return None
        return versions[-1]


class StubStageReviewService:
    def __init__(self, run_service: StubRunService) -> None:
        self.run_service = run_service

    async def approve_and_advance(
        self,
        *,
        run_service: object,
        run_id: int,
        stage_name: str,
        target_stage: str,
        reviewer: str = "agent",
        notes: str | None = None,
        workspace_id: int | None = None,
    ) -> StubRun:
        _ = run_service, reviewer, notes, workspace_id
        run = self.run_service.runs.get(run_id)
        if run is None:
            raise ValueError("Run not found")
        if run.current_stage != stage_name:
            raise ValueError(f"Stage conflict: run is now in '{run.current_stage}'")
        updated = run.model_copy(update={"current_stage": target_stage})
        self.run_service.runs[run_id] = updated
        return updated


@pytest.fixture
def script_generation_flow_services(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    project_service = StubProjectService()
    run_service = StubRunService()
    script_service = StubScriptService()
    review_service = StubStageReviewService(run_service)

    async def _check_quota(_workspace_id: int, operation_type: str) -> tuple[bool, str]:
        _ = operation_type
        return True, ""

    monkeypatch.setattr("creator_service.project_service.project_service", project_service)
    monkeypatch.setattr("creator_service.usage_service.check_workspace_quota", _check_quota)

    def fake_dispatch_generate_script(
        run_id: int,
        idea_brief: str,
        model_key: str,
        instructions: str | None,
        niche: str | None = None,
        language: str = "ko",
        task_id: str | None = None,
    ) -> str:
        _ = model_key
        prompt = idea_brief.strip()
        if instructions and instructions.strip():
            prompt = f"{prompt}\n\nAdditional instructions:\n{instructions.strip()}"

        import asyncio

        async def _mock_worker() -> None:
            generated = f"# Script\n\n{prompt}\n"
            await script_service.save_draft(
                run_id=run_id,
                source_type="generated_by_model",
                markdown_content=generated,
            )
            run = run_service.runs[run_id]
            run_service.runs[run_id] = run.model_copy(update={"current_stage": "SCRIPT_REVIEW"})

        asyncio.get_event_loop().create_task(_mock_worker())
        return "mock-script-task-1"

    for route in _iter_api_routes(app.routes):
        if route.name == "create_project":
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", project_service)
        if route.name == "create_run":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_service)
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", project_service)
        if route.name == "generate_script_trigger":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_service)
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", project_service)
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "dispatch_generate_script",
                fake_dispatch_generate_script,
            )
        if route.name == "get_script":
            monkeypatch.setitem(route.endpoint.__globals__, "script_service", script_service)
        if route.name == "approve_script":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_service)
            monkeypatch.setitem(route.endpoint.__globals__, "stage_review_service", review_service)

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, StubRun]:
        run = run_service.runs.get(run_id)
        if run is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Run not found")
        return CurrentUser(user_id=1, workspace_id=1), run

    async def _require_project_access(project_id: int) -> tuple[CurrentUser, StubProject]:
        project = project_service.projects.get(project_id)
        if project is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Project not found")
        return CurrentUser(user_id=1, workspace_id=1), project

    app.dependency_overrides[require_run_access] = _require_run_access
    app.dependency_overrides[require_project_access] = _require_project_access
    yield
    app.dependency_overrides.pop(require_run_access, None)
    app.dependency_overrides.pop(require_project_access, None)


@pytest.mark.asyncio
async def test_script_generation_vertical_slice(client, script_generation_flow_services) -> None:
    _ = script_generation_flow_services

    project_response = await client.post(
        "/api/creator/projects",
        json={
            "title": "Script Slice Project",
            "source_type": "idea",
            "idea_brief": "Create a 30-second short about ocean facts",
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    run_response = await client.post(
        f"/api/creator/projects/{project_id}/runs",
        json={"style_preset": "default"},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    trigger_response = await client.post(
        f"/api/creator/runs/{run_id}/generate-script",
        json={"model_key": "qwen3-4b", "instructions": "Keep it energetic"},
    )
    assert trigger_response.status_code == 202
    assert trigger_response.json()["current_stage"] == "SCRIPT_GENERATING"

    import asyncio

    await asyncio.sleep(0)

    script_response = await client.get(f"/api/creator/runs/{run_id}/script")
    assert script_response.status_code == 200
    body = script_response.json()
    assert body["run_id"] == run_id
    assert "ocean facts" in body["script"].lower()
    assert body["version"] == 1

    approve_response = await client.post(
        f"/api/creator/runs/{run_id}/approve-script",
        json={"reviewer": "agent", "notes": "Approved from integration test"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["current_stage"] == "VISUAL_PLAN_SETUP"


@pytest.mark.asyncio
async def test_generate_script_rejects_invalid_niche(
    client, script_generation_flow_services: None,
) -> None:
    """Pydantic validation should reject unknown niche values with 422."""
    _ = script_generation_flow_services
    project_resp = await client.post(
        "/api/creator/projects",
        json={"title": "Test", "source_type": "idea", "idea_brief": "test brief"},
    )
    assert project_resp.status_code == 201
    project_id = project_resp.json()["id"]
    run_resp = await client.post(f"/api/creator/projects/{project_id}/runs", json={})
    assert run_resp.status_code == 201
    run_id = run_resp.json()["id"]

    resp = await client.post(
        f"/api/creator/runs/{run_id}/generate-script",
        json={"model_key": "qwen3-4b", "niche": "invalid_niche_xyz"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_generate_script_rejects_invalid_language(
    client, script_generation_flow_services: None,
) -> None:
    """Pydantic validation should reject unknown language values with 422."""
    _ = script_generation_flow_services
    project_resp = await client.post(
        "/api/creator/projects",
        json={"title": "Test", "source_type": "idea", "idea_brief": "test brief"},
    )
    assert project_resp.status_code == 201
    project_id = project_resp.json()["id"]
    run_resp = await client.post(f"/api/creator/projects/{project_id}/runs", json={})
    assert run_resp.status_code == 201
    run_id = run_resp.json()["id"]

    resp = await client.post(
        f"/api/creator/runs/{run_id}/generate-script",
        json={"model_key": "qwen3-4b", "language": "xx_invalid"},
    )
    assert resp.status_code == 422
