import pytest
from creator_service.stage_review_service import StageReviewService
from .timeline_demo_support import environment


@pytest.mark.asyncio
async def test_review_insert_failure_restores_metadata_and_stage(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        seed = (await client.post("/api/creator/workspaces/1/demo-short/runs")).json()
        run_id = seed["run"]["id"]
        before = await env.runs.get_run(run_id, workspace_id=1)

        async def fail_review(row):
            raise RuntimeError("review storage unavailable")

        monkeypatch.setattr(env.reviews.storage, "create_review", fail_review)
        with pytest.raises(RuntimeError, match="review storage unavailable"):
            await client.post(
                f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
            )
    after = await env.runs.get_run(run_id, workspace_id=1)
    assert after.current_stage == before.current_stage
    assert after.metadata == before.metadata
    assert after.status == before.status
    assert env.dispatches == []


@pytest.mark.asyncio
async def test_edit_during_compilation_rejects_without_recording_approval(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        seed = (await client.post("/api/creator/workspaces/1/demo-short/runs")).json()
        run_id = seed["run"]["id"]
        timeline = await env.timelines.load_timeline(project_id=seed["seeded_project_id"], workspace_id=1)
        original_get = env.media.get_asset

        async def edit_then_resolve(asset_id: int, workspace_id: int):
            await env.timelines._storage.save_timeline(
                project_id=timeline.project_id, workspace_id=1, timeline_id=timeline.id,
                segments_json="[]", expected_revision=1,
            )
            return await original_get(asset_id, workspace_id)

        monkeypatch.setattr(env.media, "get_asset", edit_then_resolve)
        response = await client.post(
            f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
        )
    assert response.status_code == 409
    assert await env.reviews.get_latest_review(run_id, "TIMELINE_REVIEW") is None
    assert env.dispatches == []


@pytest.mark.asyncio
async def test_duplicate_approval_has_one_winner(tmp_path, monkeypatch):
    import anyio

    env = await environment(tmp_path, monkeypatch)
    responses: list[int] = []
    async with env.client as client:
        seed = (await client.post("/api/creator/workspaces/1/demo-short/runs")).json()
        run_id = seed["run"]["id"]

        async def approve():
            response = await client.post(
                f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
            )
            responses.append(response.status_code)

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(approve)
            tasks.start_soon(approve)
    assert sorted(responses) == [202, 409]
    assert len(env.dispatches) == 1


@pytest.mark.asyncio
async def test_cancel_before_approval_cas_cannot_advance_or_record_review(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        seed = (await client.post("/api/creator/workspaces/1/demo-short/runs")).json()
        run_id = seed["run"]["id"]
        original = StageReviewService.approve_and_advance

        async def cancel_then_approve(**kwargs):
            await env.runs.cancel_run(run_id, 1)
            return await original(env.reviews, **kwargs)

        monkeypatch.setattr(env.reviews, "approve_and_advance", cancel_then_approve)
        response = await client.post(
            f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
        )
    assert response.status_code == 409
    after = await env.runs.get_run(run_id, workspace_id=1)
    assert after.current_stage == "TIMELINE_REVIEW"
    assert after.status == "cancelled"
    assert "render_timeline_revision" not in after.metadata
    assert await env.reviews.get_latest_review(run_id, "TIMELINE_REVIEW") is None
    assert env.dispatches == []


@pytest.mark.asyncio
async def test_enqueue_failure_returns_to_review_with_approval_audit(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)

    def unavailable(run_id: int, render_profile: str) -> str:
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr("shorts_api.routes.creator_timeline_render.dispatch_render_video", unavailable)
    async with env.client as client:
        seed = (await client.post("/api/creator/workspaces/1/demo-short/runs")).json()
        run_id = seed["run"]["id"]
        response = await client.post(
            f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
        )
    assert response.status_code == 503
    after = await env.runs.get_run(run_id, workspace_id=1)
    assert after.current_stage == "TIMELINE_REVIEW"
    review = await env.reviews.get_latest_review(run_id, "TIMELINE_REVIEW")
    assert review["review_status"] == "approved"
    assert env.dispatches == []


@pytest.mark.asyncio
async def test_review_failure_does_not_undo_concurrent_stop(tmp_path, monkeypatch):
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        seed = (await client.post("/api/creator/workspaces/1/demo-short/runs")).json()
        run_id = seed["run"]["id"]

        async def stop_then_fail(row):
            await env.runs.stop_run(run_id, workspace_id=1)
            raise RuntimeError("review unavailable")

        monkeypatch.setattr(env.reviews.storage, "create_review", stop_then_fail)
        with pytest.raises(RuntimeError, match="Stage rollback failed"):
            await client.post(
                f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
            )
    after = await env.runs.get_run(run_id, workspace_id=1)
    assert after.status == "cancelled"
    assert after.current_stage != "RENDER_GENERATING"
    assert env.dispatches == []
    assert await env.reviews.get_latest_review(run_id, "TIMELINE_REVIEW") is None
