import json
from pathlib import Path

import anyio
import pytest
from creator_domain.exceptions import ValidationError
from creator_service.timeline_service import InMemoryTimelineStorage, TimelineService
from tasks import render_video
from tests.test_timeline_worker import WorkerFixture, worker as worker


@pytest.mark.parametrize("metadata", [
    {"render_source": "timeline"},
    {"render_source": "timeline", "render_timeline_revision": True},
    {"render_source": "timeline", "render_timeline_revision": "1"},
])
def test_worker_rejects_missing_or_invalid_approval(worker: WorkerFixture, metadata: dict[str, object]) -> None:
    async def seed() -> int:
        run_id = await worker.seed()
        await worker.runs.update_run(run_id, {"metadata_json": json.dumps(metadata)})
        return run_id

    run_id = anyio.run(seed)
    with pytest.raises(RuntimeError, match="approval|revision"):
        render_video.render_video.run(run_id=run_id)
    assert anyio.run(worker.renders.get_latest, run_id) is None


@pytest.mark.parametrize("workspace_id,project_id", [(8, 11), (7, 12)])
def test_worker_rejects_foreign_asset_reference(
    worker: WorkerFixture, monkeypatch: pytest.MonkeyPatch, workspace_id: int, project_id: int,
) -> None:
    storage = InMemoryTimelineStorage()

    async def seed() -> int:
        run_id = await worker.seed()
        timeline = await worker.timelines.load_timeline(project_id=11, workspace_id=7)
        assert timeline is not None
        original = await worker.assets.get_asset(timeline.segments[0].asset_id, 7)
        assert original is not None
        foreign = await worker.assets.create_generated_image_asset(
            workspace_id=workspace_id, project_id=project_id, filename="foreign.png",
            data=worker.backend.download_bytes(str(original.storage_key)),
        )
        segment = timeline.segments[0].model_copy(update={"asset_id": foreign.id})
        await storage.save_timeline(
            project_id=11, workspace_id=7, timeline_id="foreign", expected_revision=0,
            segments_json=json.dumps([segment.model_dump(mode="json")]),
        )
        await worker.reviews.record_approval(
            run_id, "TIMELINE_REVIEW", reviewer="7",
            notes=json.dumps({"timeline_id": "foreign", "revision": 1}),
        )
        return run_id

    run_id = anyio.run(seed)
    monkeypatch.setattr("creator_service.timeline_service.timeline_service", TimelineService(storage))
    with pytest.raises(ValidationError, match="unavailable asset"):
        render_video.render_video.run(run_id=run_id)
    assert anyio.run(worker.renders.get_latest, run_id) is None


def test_worker_fails_when_storage_object_is_missing(worker: WorkerFixture) -> None:
    async def seed() -> int:
        run_id = await worker.seed()
        timeline = await worker.timelines.load_timeline(project_id=11, workspace_id=7)
        assert timeline is not None
        asset = await worker.assets.get_asset(timeline.segments[0].asset_id, 7)
        assert asset is not None and asset.storage_key is not None
        worker.backend.delete(asset.storage_key)
        return run_id

    run_id = anyio.run(seed)
    with pytest.raises(FileNotFoundError):
        render_video.render_video.run(run_id=run_id)
    assert anyio.run(worker.renders.get_latest, run_id) is None
    row = anyio.run(worker.runs.get_run, run_id)
    assert row is not None and row["current_stage"] == "FAILED"


def test_worker_fails_on_corrupt_media_without_persisting_artifact(worker: WorkerFixture) -> None:
    async def seed() -> int:
        run_id = await worker.seed()
        timeline = await worker.timelines.load_timeline(project_id=11, workspace_id=7)
        assert timeline is not None
        asset = await worker.assets.get_asset(timeline.segments[0].asset_id, 7)
        assert asset is not None and asset.storage_key is not None
        worker.backend.upload(asset.storage_key, b"corrupt PNG")
        return run_id

    run_id = anyio.run(seed)
    with pytest.raises(RuntimeError):
        render_video.render_video.run(run_id=run_id, render_profile="fast_preview")
    assert anyio.run(worker.renders.get_latest, run_id) is None
    assert not list((worker.root / str(run_id) / "render").glob("timeline-*"))


def test_worker_rejects_missing_workspace_context(worker: WorkerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = anyio.run(worker.seed)

    async def unavailable(run_id: int) -> None:
        return None

    monkeypatch.setattr("tasks.task_runner.resolve_workspace_id_from_run", unavailable)
    with pytest.raises(RuntimeError, match="context"):
        render_video.render_video.run(run_id=run_id)
    assert anyio.run(worker.renders.get_latest, run_id) is None


def test_timeline_sources_are_cleaned_after_success(worker: WorkerFixture) -> None:
    run_id = anyio.run(worker.seed)
    result = render_video.render_video.run(run_id=run_id, render_profile="fast_preview")
    output = Path(str(result["video_path"]))
    assert output.is_file()
    assert not list(output.parent.glob("timeline-*"))
