"""Actual image-task runner with isolated storage and an event-gated provider."""

from dataclasses import dataclass, field
from pathlib import Path

import anyio
import pytest
from creator_provider.base import ImageResult
from creator_service import db, postgres_visual_asset_storage
from creator_service.postgres_run_storage import PostgresRunStorage
from creator_service.postgres_visual_asset_storage import PostgresVisualAssetStorage
from creator_service.visual_asset_service import VisualAssetService
from tasks import generate_scene_image as images
from worker_loop import run_in_worker_loop

from .terminal_validation_support import RunnerCase, runner_case as runner_case
from .test_generate_scene_image import FakeEntry, FakeRegistry, FakeVisualPlan, FakeVisualPlanService, FakeVisualScene


@dataclass
class GatedProvider:
    """Mutable invocation recorder; barriers belong to the worker's active loop."""

    entered: anyio.Event = field(default_factory=anyio.Event)
    released: anyio.Event = field(default_factory=anyio.Event)
    calls: list[str] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)
    blocked_index: int = 0
    error: Exception | None = None

    async def generate(self, prompt: str, params: dict[str, str]) -> ImageResult:
        index = len(self.calls)
        self.calls.append(prompt)
        path = Path(params["output_path"])
        path.write_bytes(b"generated-image")
        self.paths.append(path)
        if index == self.blocked_index:
            self.entered.set()
            await self.released.wait()
        if self.error is not None:
            raise self.error
        return ImageResult(image_path=str(path), width=512, height=512, model_key="sd15")


@dataclass(frozen=True, slots=True)
class SceneCase:
    runner: RunnerCase
    provider: GatedProvider
    assets: VisualAssetService
    task_id: str

    async def cancel(self) -> None:
        await self.runner.runs.cancel_run(self.runner.run_id, workspace_id=1)
        await self.runner.tracking.mark_revoked(self.task_id)

    def invoke(self, model_key: str = "sd15") -> dict[str, object]:
        task = images.generate_scene_image
        task.push_request(id=None if self.task_id.startswith("run-") else self.task_id, args=(), kwargs={}, retries=0)
        try:
            return task.run(run_id=self.runner.run_id, model_key=model_key)
        finally:
            task.pop_request()


@pytest.fixture(params=["celery", "lightweight"])
def scene_case(runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest) -> SceneCase:
    case = runner_case
    run_in_worker_loop(case.runs.storage.update_run(case.run_id, {
        "current_stage": "VISUAL_ASSET_GENERATING",
    }))
    postgres = isinstance(case.runs.storage, PostgresRunStorage)
    monkeypatch.setattr(postgres_visual_asset_storage, "get_pool", db.get_pool)
    assets = VisualAssetService(PostgresVisualAssetStorage() if postgres else None)
    provider = GatedProvider()
    plan = FakeVisualPlan(run_id=case.run_id, scenes=[
        FakeVisualScene(scene_id=f"scene-{i}", scene_index=i, prompt=f"shot-{i}")
        for i in range(2)
    ])
    monkeypatch.setattr(images, "_run_service", case.runs)
    monkeypatch.setattr(images, "_visual_asset_service", assets)
    monkeypatch.setattr(images, "_visual_plan_service", FakeVisualPlanService(plan))
    monkeypatch.setattr(images, "_ARTIFACTS_BASE", str(tmp_path))
    monkeypatch.setattr(images, "get_default_registry", lambda: FakeRegistry(
        FakeEntry(requires_gpu=False), provider,
    ))

    async def usage(*args: int, **kwargs: str) -> None:
        return None

    monkeypatch.setattr(images, "record_provider_call", usage)
    task_id = f"run-{case.run_id}" if request.param == "lightweight" else "scene-cancellation"
    return SceneCase(case, provider, assets, task_id)
