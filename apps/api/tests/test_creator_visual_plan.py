# pyright: reportMissingImports=false

from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from typing import Any, Literal

import pytest
from creator_domain.models import VisualScene
from fastapi.routing import APIRoute
from pydantic import BaseModel
from pydantic import ValidationError
from shorts_api.main import visual_plan_router
from shorts_api.routes.creator_visual_plan import PatchSceneRequest


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

    async def patch_scene(
        self,
        run_id: int,
        scene_id: str,
        updates: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> StubVisualPlan:
        """Stub patch_scene: load active plan, apply updates, save new version."""
        active = await self.get_active_plan(run_id)
        if active is None:
            raise ValueError(f"No active visual plan for run {run_id}")

        if expected_version is not None and active.version != expected_version:
            from creator_domain.exceptions import VersionConflictError

            raise VersionConflictError(run_id, expected_version, active.version)

        _patchable = {
            "prompt",
            "prompt_edited",
            "prompt_source",
            "style_tags",
            "mood",
            "composition",
        }
        unknown = set(updates.keys()) - _patchable
        if unknown:
            raise ValueError(f"Cannot patch immutable/unknown fields: {sorted(unknown)}")

        patched = False
        new_scenes: list[VisualScene] = []
        for scene in active.scenes:
            d = scene.model_dump()
            if d["scene_id"] == scene_id:
                d.update(updates)
                patched = True
            new_scenes.append(VisualScene.model_validate(d))

        if not patched:
            raise ValueError(f"Scene '{scene_id}' not found in visual plan for run {run_id}")

        return await self.save_plan(run_id, new_scenes)


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


def _make_scene(scene_id: str = "scene-1", index: int = 0) -> VisualScene:
    return VisualScene.model_validate(
        {
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
    )


def _iter_api_routes(routes: Sequence[object]) -> list[APIRoute]:
    return [route for route in routes if isinstance(route, APIRoute)]


@pytest.fixture
def stub_visual_plan_services(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[StubRunService, StubVisualPlanService]]:
    from shorts_api.auth import CurrentUser, require_run_access
    from shorts_api.main import app

    run_svc = StubRunService()
    vp_svc = StubVisualPlanService()

    for route in _iter_api_routes(visual_plan_router.routes):
        if route.name in {"get_visual_plan", "replace_visual_plan", "patch_scene"}:
            monkeypatch.setitem(route.endpoint.__globals__, "run_service", run_svc)
            monkeypatch.setitem(route.endpoint.__globals__, "visual_plan_service", vp_svc)

    async def _require_run_access(run_id: int) -> tuple[CurrentUser, StubPipelineRun]:
        run = run_svc.runs.get(run_id)
        if run is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Run not found")
        return CurrentUser(user_id=1, workspace_id=1), run

    app.dependency_overrides[require_run_access] = _require_run_access

    yield run_svc, vp_svc

    app.dependency_overrides.pop(require_run_access, None)


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
        json={"scenes": [scene.model_dump(mode="json")]},
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
        json={"scenes": [scene1.model_dump(mode="json")]},
    )

    response = await client.put(
        "/api/creator/runs/21/visual-plan",
        json={"scenes": [scene2.model_dump(mode="json")]},
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
        json={"scenes": [scene.model_dump(mode="json")]},
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
    """Empty scenes list is rejected by min_length=1 validation."""
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[23] = _make_run(23)

    response = await client.put(
        "/api/creator/runs/23/visual-plan",
        json={"scenes": []},
    )

    assert response.status_code == 422  # Pydantic min_length=1 rejects empty scenes


@pytest.mark.asyncio
async def test_replace_visual_plan_multiple_scenes(client, stub_visual_plan_services):
    """PUT with multiple scenes preserves order."""
    run_svc, _ = stub_visual_plan_services
    run_svc.runs[24] = _make_run(24)

    scenes = [_make_scene(f"scene-{i}", i) for i in range(3)]
    response = await client.put(
        "/api/creator/runs/24/visual-plan",
        json={"scenes": [scene.model_dump(mode="json") for scene in scenes]},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["scenes"]) == 3
    assert [s["scene_id"] for s in body["scenes"]] == ["scene-0", "scene-1", "scene-2"]


# ---------------------------------------------------------------------------
# PATCH /runs/{run_id}/visual-plan/scenes/{scene_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_scene_success(client, stub_visual_plan_services):
    """PATCH updates a single field and returns updated plan."""
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[30] = _make_run(30)
    scene = _make_scene("scene-1")
    vp_svc.plans[30] = [
        StubVisualPlan(
            id=1,
            run_id=30,
            version=1,
            scenes=[scene],
            created_at=datetime.now(timezone.utc),
        )
    ]

    response = await client.patch(
        "/api/creator/runs/30/visual-plan/scenes/scene-1",
        json={"prompt": "Updated prompt text"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 30
    assert body["version"] == 2
    assert body["scenes"][0]["prompt"] == "Updated prompt text"


@pytest.mark.asyncio
async def test_patch_scene_multiple_fields(client, stub_visual_plan_services):
    """PATCH can update multiple patchable fields at once."""
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[31] = _make_run(31)
    scene = _make_scene("scene-1")
    vp_svc.plans[31] = [
        StubVisualPlan(
            id=1,
            run_id=31,
            version=1,
            scenes=[scene],
            created_at=datetime.now(timezone.utc),
        )
    ]

    response = await client.patch(
        "/api/creator/runs/31/visual-plan/scenes/scene-1",
        json={
            "prompt": "New prompt",
            "mood": "dramatic",
            "style_tags": ["noir", "high-contrast"],
            "composition": "close-up",
        },
    )

    assert response.status_code == 200
    body = response.json()
    s = body["scenes"][0]
    assert s["prompt"] == "New prompt"
    assert s["mood"] == "dramatic"
    assert s["style_tags"] == ["noir", "high-contrast"]
    assert s["composition"] == "close-up"


@pytest.mark.asyncio
async def test_patch_scene_preserves_non_patched_fields(client, stub_visual_plan_services):
    """Fields not in the PATCH body remain unchanged."""
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[32] = _make_run(32)
    scene = _make_scene("scene-1")
    vp_svc.plans[32] = [
        StubVisualPlan(
            id=1,
            run_id=32,
            version=1,
            scenes=[scene],
            created_at=datetime.now(timezone.utc),
        )
    ]

    response = await client.patch(
        "/api/creator/runs/32/visual-plan/scenes/scene-1",
        json={"mood": "tense"},
    )

    assert response.status_code == 200
    s = response.json()["scenes"][0]
    assert s["prompt"] == "A person explaining something"
    assert s["style_tags"] == ["cinematic"]
    assert s["composition"] == "medium-shot"
    assert s["mood"] == "tense"


@pytest.mark.asyncio
async def test_patch_scene_run_not_found(client, stub_visual_plan_services):
    """PATCH returns 404 when run doesn't exist."""
    _, _ = stub_visual_plan_services
    response = await client.patch(
        "/api/creator/runs/999/visual-plan/scenes/scene-1",
        json={"prompt": "x"},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_scene_rejects_wrong_stage(client, stub_visual_plan_services):
    run_svc, _vp_svc = stub_visual_plan_services
    run_svc.runs[39] = _make_run(39, stage="SCRIPT_REVIEW")

    response = await client.patch(
        "/api/creator/runs/39/visual-plan/scenes/scene-1",
        json={"prompt": "x"},
    )

    assert response.status_code == 409
    assert "Cannot modify visual plan in stage" in response.json()["detail"]


@pytest.mark.asyncio
async def test_patch_scene_no_plan(client, stub_visual_plan_services):
    """PATCH returns 404 when run has no visual plan."""
    run_svc, _ = stub_visual_plan_services
    run_svc.runs[33] = _make_run(33)

    response = await client.patch(
        "/api/creator/runs/33/visual-plan/scenes/scene-1",
        json={"prompt": "x"},
    )

    assert response.status_code == 404
    assert "no active" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_scene_not_found(client, stub_visual_plan_services):
    """PATCH returns 404 when scene_id doesn't exist in the plan."""
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[34] = _make_run(34)
    scene = _make_scene("scene-1")
    vp_svc.plans[34] = [
        StubVisualPlan(
            id=1,
            run_id=34,
            version=1,
            scenes=[scene],
            created_at=datetime.now(timezone.utc),
        )
    ]

    response = await client.patch(
        "/api/creator/runs/34/visual-plan/scenes/nonexistent",
        json={"prompt": "x"},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_scene_version_conflict(client, stub_visual_plan_services):
    """PATCH returns 409 when expected_version doesn't match."""
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[35] = _make_run(35)
    scene = _make_scene("scene-1")
    vp_svc.plans[35] = [
        StubVisualPlan(
            id=1,
            run_id=35,
            version=3,
            scenes=[scene],
            created_at=datetime.now(timezone.utc),
        )
    ]

    response = await client.patch(
        "/api/creator/runs/35/visual-plan/scenes/scene-1",
        json={"prompt": "x", "expected_version": 1},
    )

    assert response.status_code == 409
    assert "version conflict" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_scene_empty_updates(client, stub_visual_plan_services):
    """PATCH returns 400 when no patchable fields provided."""
    run_svc, _ = stub_visual_plan_services
    run_svc.runs[36] = _make_run(36)

    response = await client.patch(
        "/api/creator/runs/36/visual-plan/scenes/scene-1",
        json={},
    )

    assert response.status_code == 400
    assert "no patchable" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_scene_unknown_fields(client, stub_visual_plan_services):
    """PATCH returns 422 when unknown fields are sent (extra=forbid)."""
    run_svc, _ = stub_visual_plan_services
    run_svc.runs[37] = _make_run(37)

    response = await client.patch(
        "/api/creator/runs/37/visual-plan/scenes/scene-1",
        json={"scene_id": "hacked", "prompt": "valid"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_scene_with_expected_version_match(client, stub_visual_plan_services):
    """PATCH succeeds when expected_version matches active version."""
    run_svc, vp_svc = stub_visual_plan_services
    run_svc.runs[38] = _make_run(38)
    scene = _make_scene("scene-1")
    vp_svc.plans[38] = [
        StubVisualPlan(
            id=1,
            run_id=38,
            version=2,
            scenes=[scene],
            created_at=datetime.now(timezone.utc),
        )
    ]

    response = await client.patch(
        "/api/creator/runs/38/visual-plan/scenes/scene-1",
        json={"prompt": "Updated", "expected_version": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 3
    assert body["scenes"][0]["prompt"] == "Updated"


def test_patch_scene_request_rejects_overlong_fields() -> None:
    with pytest.raises(ValidationError):
        PatchSceneRequest(mood="x" * 257)
    with pytest.raises(ValidationError):
        PatchSceneRequest(composition="x" * 257)
    with pytest.raises(ValidationError):
        PatchSceneRequest(style_tags=["x" * 257])
