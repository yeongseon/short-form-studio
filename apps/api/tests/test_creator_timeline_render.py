import json

import pytest
from creator_domain.models import Timeline
from .timeline_demo_support import environment


@pytest.mark.asyncio
async def test_explicit_approval_dispatches_persisted_revision(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        seeded = await client.post("/api/creator/workspaces/1/demo-short/runs")
        assert seeded.status_code == 201
        run_id = seeded.json()["run"]["id"]
        response = await client.post(
            f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
        )
    assert response.status_code == 202
    assert env.dispatches == [(run_id, "shorts_default")]
    run = await env.runs.get_run(run_id, workspace_id=1)
    assert run is not None and run.current_stage == "RENDER_GENERATING"
    assert run.metadata["render_timeline_revision"] == 1
    assert run.metadata["render_source"] == "timeline"
    review = await env.reviews.get_latest_review(run_id, "TIMELINE_REVIEW")
    assert review is not None and review["reviewer"] == "17"
    assert review["review_status"] == "approved"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stale", "empty", "foreign_asset", "legacy", "cancelled"])
async def test_invalid_approval_has_no_side_effects(tmp_path, monkeypatch, failure):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        seed = (await client.post("/api/creator/workspaces/1/demo-short/runs")).json()
        run_id = seed["run"]["id"]
        revision = 1
        status = 409
        if failure in {"empty", "foreign_asset"}:
            timeline = await env.timelines.load_timeline(project_id=seed["seeded_project_id"], workspace_id=1)
            segments = [] if failure == "empty" else [timeline.segments[0].model_copy(update={"asset_id": 999})]
            corrupted = Timeline(id=timeline.id, project_id=timeline.project_id, segments=segments)
            await env.timelines._storage.save_timeline(
                project_id=timeline.project_id, workspace_id=1, timeline_id=timeline.id,
                segments_json=json.dumps([s.model_dump(mode="json") for s in corrupted.segments]),
                expected_revision=1,
            )
            revision = 2
            status = 400
        if failure == "stale":
            revision = 0
        if failure == "legacy":
            await env.runs.storage.update_run(run_id, {"current_stage": "SCRIPT_REVIEW"}, workspace_id=1)
        if failure == "cancelled":
            await env.runs.cancel_run(run_id, 1)
        before = await env.runs.get_run(run_id, workspace_id=1)
        response = await client.post(
            f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": revision},
        )
    assert response.status_code == status
    assert await env.runs.get_run(run_id, workspace_id=1) == before
    assert env.dispatches == []
    assert await env.reviews.get_latest_review(run_id, "TIMELINE_REVIEW") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"expected_revision": -1}, {"expected_revision": True},
                                    {"expected_revision": "1"}, {"expected_revision": 1, "reviewer": "other"}])
async def test_invalid_request_cannot_dispatch(tmp_path, monkeypatch, payload):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        seed = (await client.post("/api/creator/workspaces/1/demo-short/runs")).json()
        run_id = seed["run"]["id"]
        response = await client.post(f"/api/creator/runs/{run_id}/approve-timeline-render", json=payload)
    assert response.status_code == 422
    assert env.dispatches == []
    assert await env.reviews.get_latest_review(run_id, "TIMELINE_REVIEW") is None


@pytest.mark.asyncio
async def test_auth_and_cross_workspace_return_no_approval(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        seed = (await client.post("/api/creator/workspaces/1/demo-short/runs")).json()
        run_id = seed["run"]["id"]
        env.runs.storage._rows[run_id]["workspace_id"] = 2  # workspace_id is storage-owned; move the fixture row directly.
        response = await client.post(
            f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
        )
        assert response.status_code == 404
        env.app.dependency_overrides.clear()
        response = await client.post(
            f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
        )
        assert response.status_code == 401
    assert env.dispatches == []
    assert await env.reviews.get_latest_review(run_id, "TIMELINE_REVIEW") is None
