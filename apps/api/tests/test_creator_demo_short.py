import pytest
from creator_domain.models import MediaOrigin

from .timeline_demo_support import environment


@pytest.mark.asyncio
async def test_workspace_plan_discloses_offline_costs_without_persisting(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        response = await client.get("/api/creator/workspaces/1/demo-short/plan")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["required_approvals"] == ["TIMELINE_REVIEW", "FINAL_REVIEW"]
    assert body["estimated_total_cost_usd"] == 0
    assert body["required_provider_env_vars"] == []
    assert body["sample_project_id"] is None
    assert body["sample_timeline_id"] is None
    assert body["external_exposure"] == "none"
    assert await env.runs.list_runs_by_workspace(1) == []


@pytest.mark.asyncio
async def test_seed_endpoint_persists_real_assets_timeline_and_run(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        response = await client.post("/api/creator/workspaces/1/demo-short/runs")
    assert response.status_code == 201
    body = response.json()
    run = await env.runs.get_run(body["run"]["id"], workspace_id=1)
    assert run is not None and run.current_stage == "TIMELINE_REVIEW"
    assert run.status == "paused" and run.project_id == body["seeded_project_id"]
    timeline = await env.timelines.load_timeline(project_id=run.project_id, workspace_id=1)
    assert timeline is not None and timeline.id == body["timeline_id"]
    assert len(timeline.segments) == 2
    origins: set[MediaOrigin] = set()
    payloads: set[bytes] = set()
    for segment in timeline.segments:
        asset = await env.media.get_asset(segment.asset_id, 1)
        assert asset is not None and asset.project_id == run.project_id
        assert asset.metadata["license"] == "CC0-1.0"
        assert asset.metadata["provenance"] == "synthetic"
        assert await env.media.get_asset(asset.id, 99) is None
        data = (tmp_path / asset.storage_key).read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        payloads.add(data)
        origins.add(asset.origin)
    assert origins == {MediaOrigin.UPLOADED, MediaOrigin.GENERATED}
    assert len(payloads) == 2
    assert env.dispatches == []
    assert await env.reviews.get_latest_review(run.id, "TIMELINE_REVIEW") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("path,method", [("plan", "get"), ("runs", "post")])
async def test_workspace_demo_rejects_cross_workspace_and_anonymous(tmp_path, monkeypatch, path, method):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        response = await client.request(method, f"/api/creator/workspaces/99/demo-short/{path}")
        assert response.status_code == 404
        env.app.dependency_overrides.clear()
        response = await client.request(method, f"/api/creator/workspaces/1/demo-short/{path}")
        assert response.status_code == 401
    assert await env.runs.list_runs_by_workspace(1) == []


@pytest.mark.asyncio
async def test_project_plan_compatibility_preserves_ownership(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)
    project = await env.projects.create_project(
        title="Existing", source_type="idea", idea_brief="Example", workspace_id=1,
    )
    async with env.client as client:
        response = await client.get(f"/api/creator/projects/{project.id}/demo-short/plan")
        assert response.status_code == 200
        assert response.json()["sample_project_id"] is None
        response = await client.get("/api/creator/projects/999/demo-short/plan")
        assert response.status_code == 404
