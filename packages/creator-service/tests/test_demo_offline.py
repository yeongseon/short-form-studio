from pathlib import Path

import pytest
from creator_domain.models import EncodingProfile, MediaOrigin, OutputSpec
from creator_service.demo_seed import seed_demo_short
from creator_service.demo_short_flow import build_demo_short_plan
from creator_service.media_asset_service import InMemoryMediaAssetStorage, MediaAssetService
from creator_service.object_storage import LocalStorageBackend
from creator_service.project_service import InMemoryProjectStorage, ProjectService
from creator_service.run_service import InMemoryRunStorage, RunService
from creator_service.timeline_compiler import compile_timeline_to_render_plan
from creator_service.timeline_service import TimelineService


def test_plan_is_offline_without_synthetic_database_ids() -> None:
    # Given no provider setup, when planning an offline sample.
    plan = build_demo_short_plan()
    # Then no provider or fictional persisted project is disclosed.
    assert plan.ready
    assert plan.estimated_total_cost_usd == 0
    assert plan.required_provider_env_vars == ()
    assert plan.sample_project_id is None
    assert plan.sample_timeline_id is None
    assert [stage.value for stage in plan.required_approvals] == [
        "TIMELINE_REVIEW", "FINAL_REVIEW",
    ]


@pytest.mark.asyncio
async def test_real_seed_saves_renderable_png_and_pauses_for_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given real services backed by isolated local/in-memory persistence.
    media = MediaAssetService(LocalStorageBackend(str(tmp_path)), InMemoryMediaAssetStorage())
    monkeypatch.setattr("creator_service.media_asset_service.media_asset_service", media)
    timelines = TimelineService()
    runs = RunService(InMemoryRunStorage())
    projects = ProjectService(InMemoryProjectStorage())
    # When seeding without any provider call.
    result = await seed_demo_short(
        workspace_id=7, project_service=projects, media_asset_service=media,
        timeline_service=timelines, run_service=runs,
    )
    # Then the persisted content compiles and still needs explicit approval.
    assert result.run.current_stage == "TIMELINE_REVIEW"
    assert result.run.status == "paused"
    assert result.run.metadata == {"demo": True, "sample_backed": True, "render_source": "timeline"}
    timeline = await timelines.load_timeline(project_id=result.project_id, workspace_id=7)
    assert timeline is not None and timeline.revision == 1
    assert timeline.id == result.timeline_id
    asset = await media.get_asset(timeline.segments[0].asset_id, 7)
    assert asset is not None and asset.origin == MediaOrigin.GENERATED
    assert asset.project_id == result.project_id
    assert (tmp_path / asset.storage_key).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    plan = await compile_timeline_to_render_plan(
        timeline, workspace_id=7, output_spec=OutputSpec.preset("short_vertical"),
        encoding_profile=EncodingProfile.by_name("preview"), asset_resolver=media,
    )
    assert len(plan.segments) == 2
    assert len({segment.source for segment in plan.segments}) == 2
    assert await media.get_asset(asset.id, 8) is None
    assert await runs.get_run(result.run.id, workspace_id=8) is None
