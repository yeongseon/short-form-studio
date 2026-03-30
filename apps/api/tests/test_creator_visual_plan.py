# pyright: reportMissingImports=false

from datetime import datetime, timezone
from typing import Any, Literal

import pytest
from models.visual_plan import VisualScene
from pydantic import BaseModel
from shorts_api.main import visual_plan_router


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
        self.runs: dict[int, StubPipelineRun] = {}

    async def get_run(self, run_id: int) -> StubPipelineRun | None:
        return self.runs.get(run_id)


class StubVisualPlan(BaseModel):
    id: int
    run_id: int
    version: int
    scenes: list[VisualScene]
    created_at: datetime


class StubVisualPlanService:
    def __init__(self) -> None:
        self.plans: dict[int, list[StubVisualPlan]] = {}
        self._next_id = 1
        self.save_calls: list[dict[str, Any]] = []

    async def get_active_plan(self, run_id: int) -> StubVisualPlan | None:
        versions = self.plans.get(run_id, [])
        if not versions:
            return None
        return max(versions, key=lambda p: p.version)

    async def save_plan(self, run_id: int, scenes: list[Any]) -> StubVisualPlan:
        self.save_calls.append({"run_id": run_id, "scenes": scenes})
        versions = self.plans.setdefault(run_id, [])
        next_version = max((p.version for p in versions), default=0) + 1
        plan = StubVisualPlan(
            id=self._next_id,
            run_id=run_id,
            version=next_version,
            scenes=[VisualScene.model_validate(s) for s in scenes],
            created_at=datetime.now(timezone.utc),
        )
        self._next_id += 1
        versions.append(plan)
        return plan


def _make_run(run_id: int, stage: str = "VISUAL_PLAN_REVIEW") -> StubPipelineRun:
    now = datetime.now(timezone.utc)
    return StubPipelineRun(
        id=run_id,
        project_id=1,
        current_stage=stage,
        status="running",
        created_at=now,
        updated_at=now,
    )


def _make_scene(scene_id: str = "scene-1", index: int = 0) -> dict[str, Any]:
    return {
        "scene_id": scene_id,
        "section_id": "sec-1",
        "scene_index": index,
        "section_type": "narration",
        "original_text": "Sample narration text",
        "prompt": "A person explaining something",
        "prompt_edited": False,
        "prompt_source": "auto_generated",
        "style_tags": ["cinematic"],
        "mood": "neutral",
        "composition": "medium-shot",
        "generation_status": "pending",
        "latest_asset_id": None,
    }


@pytest.fixture
def stub_visual_plan_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunService, StubVisualPlanService]:
    run_svc = StubRunService()
    vp_svc = StubVisualPlanService()

    for route in visual_plan_router.routes:
        if route.name in {"get_visual_plan", "replace_visual_plan"}:
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "visual_plan_service", vp_svc)

    return run_svc, vp_svc


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/visual-plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_visual_plan_success(client, stub_visual_plan_services):
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[10] = _make_run(10)
    scene = _make_scene()
    vp_svc.plans[10] = [
        StubVisualPlan(
            id=1,
            run_id=10,
            version=1,
            scenes=[scene],
            created_at=datetime.now(timezone.utc),
        )
    ]

    response = await client.get("/api/creator/runs/10/visual-plan")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 10
    assert body["version"] == 1
    assert len(body["scenes"]) == 1
    assert body["scenes"][0]["scene_id"] == "scene-1"
    assert body["scenes"][0]["prompt"] == "A person explaining something"


@pytest.mark.asyncio
async def test_get_visual_plan_run_not_found(client, stub_visual_plan_services):
    _, _ = stub_visual_plan_services
    response = await client.get("/api/creator/runs/999/visual-plan")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_visual_plan_no_plan(client, stub_visual_plan_services):
    run_svc, _ = stub_visual_plan_services
    run_svc.runs[11] = _make_run(11)

    response = await client.get("/api/creator/runs/11/visual-plan")

    assert response.status_code == 404
    assert "no visual plan" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_visual_plan_latest_version(client, stub_visual_plan_services):
    """When multiple versions exist, GET returns the latest."""
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[12] = _make_run(12)
    scene_v1 = _make_scene("scene-v1")
    scene_v2 = _make_scene("scene-v2")
    now = datetime.now(timezone.utc)
    vp_svc.plans[12] = [
        StubVisualPlan(id=1, run_id=12, version=1, scenes=[scene_v1], created_at=now),
        StubVisualPlan(id=2, run_id=12, version=2, scenes=[scene_v2], created_at=now),
    ]

    response = await client.get("/api/creator/runs/12/visual-plan")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["scenes"][0]["scene_id"] == "scene-v2"


# ---------------------------------------------------------------------------
# PUT /runs/{run_id}/visual-plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_visual_plan_success(client, stub_visual_plan_services):
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[20] = _make_run(20)

    scene = _make_scene("scene-new")
    response = await client.put(
        "/api/creator/runs/20/visual-plan",
        json={"scenes": [scene]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 20
    assert body["version"] == 1
    assert len(body["scenes"]) == 1
    assert body["scenes"][0]["scene_id"] == "scene-new"
    assert len(vp_svc.save_calls) == 1
    assert vp_svc.save_calls[0]["run_id"] == 20


@pytest.mark.asyncio
async def test_replace_visual_plan_version_increment(client, stub_visual_plan_services):
    """Second PUT creates version 2."""
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[21] = _make_run(21)

    scene1 = _make_scene("scene-a")
    scene2 = _make_scene("scene-b")

    await client.put(
        "/api/creator/runs/21/visual-plan",
        json={"scenes": [scene1]},
    )

    response = await client.put(
        "/api/creator/runs/21/visual-plan",
        json={"scenes": [scene2]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["scenes"][0]["scene_id"] == "scene-b"
    assert len(vp_svc.save_calls) == 2


@pytest.mark.asyncio
async def test_replace_visual_plan_run_not_found(client, stub_visual_plan_services):
    _, _ = stub_visual_plan_services
    scene = _make_scene()
    response = await client.put(
        "/api/creator/runs/999/visual-plan",
        json={"scenes": [scene]},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_replace_visual_plan_invalid_scene(client, stub_visual_plan_services):
    """Invalid scene data returns 400."""
    run_svc, _ = stub_visual_plan_services
    run_svc.runs[22] = _make_run(22)

    response = await client.put(
        "/api/creator/runs/22/visual-plan",
        json={"scenes": [{"invalid": "data"}]},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_replace_visual_plan_empty_scenes(client, stub_visual_plan_services):
    """Empty scenes list is valid — clears the plan."""
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[23] = _make_run(23)

    response = await client.put(
        "/api/creator/runs/23/visual-plan",
        json={"scenes": []},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scenes"] == []
    assert body["version"] == 1
    assert len(vp_svc.save_calls) == 1


@pytest.mark.asyncio
async def test_replace_visual_plan_multiple_scenes(client, stub_visual_plan_services):
    """PUT with multiple scenes preserves order."""
    run_svc, _ = stub_visual_plan_services
    run_svc.runs[24] = _make_run(24)

    scenes = [_make_scene(f"scene-{i}", i) for i in range(3)]
    response = await client.put(
        "/api/creator/runs/24/visual-plan",
        json={"scenes": scenes},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["scenes"]) == 3
    assert [s["scene_id"] for s in body["scenes"]] == ["scene-0", "scene-1", "scene-2"]
