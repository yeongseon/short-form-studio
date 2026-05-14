# pyright: reportMissingImports=false

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime, timezone

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel
from creator_domain.models import VisualScene
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


class StubVisualPlan(BaseModel):
    id: int
    run_id: int
    version: int
    scenes: list[VisualScene]
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
        self, run_id: int, updates: dict[str, object], expected_stages: frozenset[str]
    ) -> tuple[bool, dict[str, object] | None]:
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


class StubVisualPlanService:
    def __init__(self) -> None:
        self.plans: dict[int, list[StubVisualPlan]] = {}
        self.next_id = 1

    async def save_plan(self, run_id: int, scenes: list[dict[str, object]]) -> StubVisualPlan:
        versions = self.plans.setdefault(run_id, [])
        plan = StubVisualPlan(
            id=self.next_id,
            run_id=run_id,
            version=len(versions) + 1,
            scenes=[VisualScene.model_validate(scene) for scene in scenes],
            created_at=datetime.now(timezone.utc),
        )
        self.next_id += 1
        versions.append(plan)
        return plan

    async def get_active_plan(self, run_id: int) -> StubVisualPlan | None:
        versions = self.plans.get(run_id, [])
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
def visual_plan_flow_services(monkeypatch: pytest.MonkeyPatch) -> Iterator[StubRunService]:
    project_service = StubProjectService()
    run_service = StubRunService()
    visual_plan_service = StubVisualPlanService()
    review_service = StubStageReviewService(run_service)

    async def _check_quota(_workspace_id: int, operation_type: str) -> tuple[bool, str]:
        _ = operation_type
        return True, ""

    monkeypatch.setattr("creator_service.project_service.project_service", project_service)
    monkeypatch.setattr("creator_service.usage_service.check_workspace_quota", _check_quota)

    def fake_dispatch_generate_visual_plan(
        run_id: int, model_key: str, style_preset: str | None
    ) -> str:
        _ = model_key, style_preset
        scene = {
            "scene_id": "scene-sec-0",
            "section_id": "sec-0",
            "scene_index": 0,
            "section_type": "narration",
            "original_text": "A concise fact about ocean life.",
            "prompt": "A cinematic underwater shot with sun rays and fish",
            "prompt_edited": False,
            "prompt_source": "auto_generated",
            "style_tags": ["cinematic"],
            "mood": "calm",
            "composition": "wide-shot",
            "generation_status": "pending",
            "latest_asset_id": None,
        }

        import asyncio

        async def _mock_worker() -> None:
            await visual_plan_service.save_plan(run_id=run_id, scenes=[scene])
            run = run_service.runs[run_id]
            run_service.runs[run_id] = run.model_copy(
                update={"current_stage": "VISUAL_PLAN_REVIEW"}
            )

        asyncio.get_event_loop().create_task(_mock_worker())
        return "mock-visual-plan-task-1"

    for route in _iter_api_routes(app.routes):
        if route.name == "create_project":
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", project_service)
        if route.name == "create_run":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_service)
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", project_service)
        if route.name == "approve_script":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_service)
            monkeypatch.setitem(route.endpoint.__globals__, "stage_review_service", review_service)
        if route.name == "generate_visual_plan_trigger":
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_service)
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "dispatch_generate_visual_plan",
                fake_dispatch_generate_visual_plan,
            )
        if route.name == "get_visual_plan":
            monkeypatch.setitem(
                route.endpoint.__globals__, "visual_plan_service", visual_plan_service
            )
        if route.name == "approve_visual_plan":
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
    yield run_service
    app.dependency_overrides.pop(require_run_access, None)
    app.dependency_overrides.pop(require_project_access, None)


@pytest.mark.asyncio
async def test_visual_plan_flow_vertical_slice(client, visual_plan_flow_services) -> None:
    run_service = visual_plan_flow_services

    project_response = await client.post(
        "/api/creator/projects",
        json={
            "title": "Visual Plan Slice Project",
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

    run_service.runs[run_id] = run_service.runs[run_id].model_copy(
        update={"current_stage": "SCRIPT_REVIEW"}
    )

    approve_script_response = await client.post(
        f"/api/creator/runs/{run_id}/approve-script",
        json={"reviewer": "agent", "notes": "Script approved for visual planning"},
    )
    assert approve_script_response.status_code == 200
    assert approve_script_response.json()["current_stage"] == "VISUAL_PLAN_SETUP"

    trigger_response = await client.post(
        f"/api/creator/runs/{run_id}/generate-visual-plan",
        json={"model_key": "qwen3-4b", "style_preset": "cinematic"},
    )
    assert trigger_response.status_code == 202
    assert trigger_response.json()["current_stage"] == "VISUAL_PLAN_GENERATING"

    import asyncio

    await asyncio.sleep(0)

    visual_plan_response = await client.get(f"/api/creator/runs/{run_id}/visual-plan")
    assert visual_plan_response.status_code == 200
    body = visual_plan_response.json()
    assert body["run_id"] == run_id
    assert body["version"] == 1
    assert body["scenes"][0]["scene_id"] == "scene-sec-0"
    assert "underwater" in body["scenes"][0]["prompt"].lower()

    approve_visual_plan_response = await client.post(
        f"/api/creator/runs/{run_id}/approve-visual-plan",
        json={"reviewer": "agent", "notes": "Visual plan approved from integration test"},
    )
    assert approve_visual_plan_response.status_code == 200
    assert approve_visual_plan_response.json()["current_stage"] == "VISUAL_ASSET_GENERATING"
