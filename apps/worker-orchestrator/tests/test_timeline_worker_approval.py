import json
from pathlib import Path

import anyio
import pytest
from creator_service.ffmpeg_service import RenderInput
from tasks import render_video
from tasks.render_materializer import RenderSourceError
from tasks.timeline_render import TimelineFFmpegService
from tests.test_timeline_worker import WorkerFixture, worker as worker


@pytest.fixture
def forbid_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(self: TimelineFFmpegService, inputs: RenderInput, output: Path) -> Path:
        pytest.fail("An unapproved timeline reached FFmpeg")

    monkeypatch.setattr(TimelineFFmpegService, "render", forbidden)


def test_forged_metadata_without_review_is_rejected(worker: WorkerFixture, forbid_ffmpeg: None) -> None:
    # Given valid-looking metadata without a persisted review.
    async def seed() -> int:
        return await worker.seed(approved=False)

    run_id = anyio.run(seed)
    # When the production worker runs, then approval fails before FFmpeg.
    with pytest.raises(RenderSourceError, match="approval"):
        render_video.render_video.run(run_id=run_id, render_profile="fast_preview")
    assert anyio.run(worker.renders.get_latest, run_id) is None


@pytest.mark.parametrize("notes", [
    json.dumps({"timeline_id": "another-timeline", "revision": 1}),
    json.dumps({"timeline_id": "worker-test", "revision": 2}),
    json.dumps({"timeline_id": "worker-test", "revision": True}),
    json.dumps({"timeline_id": "worker-test", "revision": "1"}),
    json.dumps({"revision": 1}),
    "not-json", "null", "[]", None,
])
def test_review_must_bind_saved_timeline_and_revision(
    worker: WorkerFixture, forbid_ffmpeg: None, notes: str | None,
) -> None:
    # Given an actual approval row with invalid or mismatched notes.
    async def seed() -> int:
        run_id = await worker.seed(approved=False)
        await worker.reviews.record_approval(run_id, "TIMELINE_REVIEW", reviewer="7", notes=notes)
        return run_id

    run_id = anyio.run(seed)
    # When rendering is attempted, then the row cannot authorize FFmpeg.
    with pytest.raises(RenderSourceError, match="approval"):
        render_video.render_video.run(run_id=run_id, render_profile="fast_preview")
    assert anyio.run(worker.renders.get_latest, run_id) is None


@pytest.mark.parametrize("other_run,stage,status", [
    (True, "TIMELINE_REVIEW", "approved"),
    (False, "FINAL_REVIEW", "approved"),
    (False, "TIMELINE_REVIEW", "rejected"),
    (False, "TIMELINE_REVIEW", "pending"),
])
def test_review_must_be_approved_for_same_run_and_stage(
    worker: WorkerFixture, forbid_ffmpeg: None, other_run: bool, stage: str, status: str,
) -> None:
    # Given a stored review for another run/stage or a non-approved decision.
    async def seed() -> int:
        run_id = await worker.seed(approved=False)
        await worker.reviews.storage.create_review({
            "run_id": run_id + 1 if other_run else run_id, "stage_name": stage,
            "review_status": status, "reviewer": "7",
            "notes": json.dumps({"timeline_id": "worker-test", "revision": 1}),
        })
        return run_id

    run_id = anyio.run(seed)
    # When rendering is attempted, then this decision grants no authority.
    with pytest.raises(RenderSourceError, match="approval"):
        render_video.render_video.run(run_id=run_id, render_profile="fast_preview")
    assert anyio.run(worker.renders.get_latest, run_id) is None


def test_latest_rejection_supersedes_older_approval(worker: WorkerFixture, forbid_ffmpeg: None) -> None:
    # Given an earlier approval followed by a rejection.
    async def seed() -> int:
        run_id = await worker.seed()
        await worker.reviews.storage.create_review({
            "run_id": run_id, "stage_name": "TIMELINE_REVIEW", "review_status": "rejected",
            "reviewer": "7", "notes": json.dumps({"timeline_id": "worker-test", "revision": 1}),
        })
        return run_id

    run_id = anyio.run(seed)
    # When rendering is attempted, then the older approval cannot be reused.
    with pytest.raises(RenderSourceError, match="approval"):
        render_video.render_video.run(run_id=run_id, render_profile="fast_preview")
    assert anyio.run(worker.renders.get_latest, run_id) is None
