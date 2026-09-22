import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from creator_service.object_storage import LocalStorageBackend
from creator_service.render_profile import RenderProfile
from tasks.task_runner import TaskContext
from tasks.timeline_render import render_saved_timeline

from .timeline_demo_support import environment


@pytest.mark.asyncio
async def test_approved_seed_renders_both_distinct_synthetic_scenes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a user-loaded sample and explicit approval through the real API.
    env = await environment(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setattr("creator_service.object_storage._storage_backend", LocalStorageBackend(str(tmp_path)))
    async with env.client as client:
        response = await client.post("/api/creator/workspaces/1/demo-short/runs")
        assert response.status_code == 201
        run_id = response.json()["run"]["id"]
        approval = await client.post(
            f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
        )
        assert approval.status_code == 202
    run = await env.runs.get_run(run_id, workspace_id=1)
    assert run is not None and run.current_stage == "RENDER_GENERATING"
    context = TaskContext(
        run_id=run.id, task_id="sample-render", run={"metadata": run.metadata},
        workspace_id=1, project_id=run.project_id, start_time=datetime.now(timezone.utc),
    )
    output = tmp_path / "sample.mp4"

    # When the production approval validator/compiler/materializer/FFmpeg path runs.
    count = await render_saved_timeline(context, RenderProfile.fast_preview(), output)

    # Then both source colors appear in their own scenes (allowing lossy H.264 rounding).
    assert count == 2
    for timestamp, color in (("1", (32, 48, 80)), ("3", (24, 192, 208))):
        pixels = subprocess.run([
            "ffmpeg", "-v", "error", "-ss", timestamp, "-i", str(output),
            "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ], check=True, capture_output=True, timeout=30).stdout
        assert tuple(pixels) == pytest.approx(color, abs=8)
