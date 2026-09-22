from pathlib import Path

import pytest
from tasks.render_video import execute_render
from tasks.render_materializer import RenderSourceError
from tasks.task_runner import TaskContext


@pytest.mark.asyncio
async def test_unapproved_timeline_cannot_render_after_public_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Cross-runtime setup: API routes restart; this worker suite owns rejection.
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root))
    from apps.api.tests.timeline_demo_support import environment
    from shorts_api.routes import creator_runs_core, creator_runs_scene_assets

    # Given a real seeded canonical run and the public lifecycle/render routers.
    env = await environment(tmp_path, monkeypatch)
    for module in (creator_runs_core, creator_runs_scene_assets):
        env.app.include_router(module.router, prefix="/api/creator")
        monkeypatch.setattr(module, "run_service", env.runs)
    async with env.client as client:
        seeded = await client.post("/api/creator/workspaces/1/demo-short/runs")
        assert seeded.status_code == 201
        run_id = seeded.json()["run"]["id"]
        blocked = await client.post(f"/api/creator/runs/{run_id}/render", json={})
        assert blocked.status_code == 409
        # When a caller uses the actual restart API to enter a render-eligible stage.
        restarted = await client.post(
            f"/api/creator/runs/{run_id}/restart", json={"stage": "RENDER_GENERATING"},
        )
        assert restarted.status_code == 200, restarted.text
        row = await env.runs.storage.get_run(run_id, workspace_id=1)
        assert row is not None
        ctx = TaskContext(run_id=run_id, task_id="unapproved-restart", run=row,
                          workspace_id=1, project_id=seeded.json()["seeded_project_id"], start_time=0.0)
        # Then the production worker retains canonical routing and rejects before rendering.
        assert restarted.json()["metadata"]["render_source"] == "timeline"
        with pytest.raises(RenderSourceError, match="approved revision"):
            await execute_render(ctx)
    assert await env.reviews.get_latest_review(run_id, "TIMELINE_REVIEW") is None
    assert list(tmp_path.rglob("*.mp4")) == []
