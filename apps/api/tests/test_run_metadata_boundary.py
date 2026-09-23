from pathlib import Path

import pytest
from shorts_api.routes import creator_runs_core

from .timeline_demo_support import environment


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [
    {"render_source": "timeline", "render_timeline_revision": 1},
    {"render_source": None},
    {"render_timeline_revision": 1},
    {"approval": {"revision": 1, "reviewer": "17"}},
    {"approvals": ["TIMELINE_REVIEW"]},
    {"approved": True},
    {"approved_by": "17"},
    {"approved_at": "2026-09-22T00:00:00Z"},
    {"approval_id": 1},
    {"timeline_approval": {"revision": 1}},
    {"timeline_approved_revision": 1},
    {"render_approval": {"revision": 1}},
    {"review_status": "approved"},
    {"review_stage": "TIMELINE_REVIEW"},
    {"reviewer": "17"},
])
async def test_reserved_metadata_is_rejected_before_run_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: dict[str, object],
) -> None:
    env = await environment(tmp_path, monkeypatch)
    env.app.include_router(creator_runs_core.router, prefix="/api/creator")
    monkeypatch.setattr(creator_runs_core, "run_service", env.runs)
    project = await env.projects.create_project(
        title="Owned", source_type="idea", idea_brief="Test", workspace_id=1,
    )
    async with env.client as client:
        response = await client.post(
            f"/api/creator/projects/{project.id}/runs",
            json={"metadata": {"campaign": "safe", **metadata}},
        )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "metadata"]
    assert await env.runs.list_runs_by_project(project.id, workspace_id=1) == []
    assert env.dispatches == []


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [None, {}, {"campaign": "launch", "tags": ["test"], "custom": {"color": "blue"}}])
async def test_harmless_metadata_survives_generic_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata: dict[str, object] | None,
) -> None:
    env = await environment(tmp_path, monkeypatch)
    env.app.include_router(creator_runs_core.router, prefix="/api/creator")
    monkeypatch.setattr(creator_runs_core, "run_service", env.runs)
    project = await env.projects.create_project(
        title="Owned", source_type="idea", idea_brief="Test", workspace_id=1,
    )
    async with env.client as client:
        response = await client.post(
            f"/api/creator/projects/{project.id}/runs", json={"metadata": metadata},
        )
    assert response.status_code == 201
    runs = await env.runs.list_runs_by_project(project.id, workspace_id=1)
    assert len(runs) == 1
    assert runs[0].metadata == metadata
    assert runs[0].current_stage == "IDEA_READY"


@pytest.mark.asyncio
async def test_server_owned_demo_metadata_still_reaches_explicit_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = await environment(tmp_path, monkeypatch)
    async with env.client as client:
        seeded = await client.post("/api/creator/workspaces/1/demo-short/runs")
        assert seeded.status_code == 201
        run_id = seeded.json()["run"]["id"]
        assert seeded.json()["run"]["metadata"]["render_source"] == "timeline"
        response = await client.post(
            f"/api/creator/runs/{run_id}/approve-timeline-render", json={"expected_revision": 1},
        )
    assert response.status_code == 202
    run = await env.runs.get_run(run_id, workspace_id=1)
    assert run is not None and run.metadata is not None
    assert run.metadata["render_timeline_revision"] == 1
    review = await env.reviews.get_latest_review(run_id, "TIMELINE_REVIEW")
    assert review is not None and review["review_status"] == "approved"
    assert env.dispatches == [(run_id, "shorts_default")]
