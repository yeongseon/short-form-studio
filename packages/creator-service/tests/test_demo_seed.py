from io import BytesIO
from pathlib import Path

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import EncodingProfile, MediaAsset, MediaOrigin, MediaType, OutputSpec, Timeline
from creator_service.demo_seed import seed_demo_short
from creator_service.media_asset_service import InMemoryMediaAssetStorage, MediaAssetService
from creator_service.object_storage import LocalStorageBackend
from creator_service.project_service import InMemoryProjectStorage, ProjectService
from creator_service.run_service import InMemoryRunStorage, RunService
from creator_service.timeline_service import TimelineService
from creator_service.timeline_compiler import compile_timeline_to_render_plan
from PIL import Image


@pytest.mark.asyncio
async def test_repeated_seeds_create_distinct_owned_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given real services with isolated metadata and byte storage.
    media = MediaAssetService(LocalStorageBackend(str(tmp_path)), InMemoryMediaAssetStorage())
    monkeypatch.setattr("creator_service.media_asset_service.media_asset_service", media)
    projects = ProjectService(InMemoryProjectStorage())
    timelines = TimelineService()
    runs = RunService(InMemoryRunStorage())
    first = await seed_demo_short(
        workspace_id=7, project_service=projects, media_asset_service=media,
        timeline_service=timelines, run_service=runs,
    )
    original_project = await projects.get_project(first.project_id, workspace_id=7)
    original_timeline = await timelines.load_timeline(project_id=first.project_id, workspace_id=7)
    original_assets = await media.list_assets(workspace_id=7, project_id=first.project_id)
    # When loading the sample again, existing content must remain immutable.
    second = await seed_demo_short(
        workspace_id=7, project_service=projects, media_asset_service=media,
        timeline_service=timelines, run_service=runs,
    )
    assert first.project_id != second.project_id
    assert first.timeline_id != second.timeline_id
    assert await projects.get_project(first.project_id, workspace_id=7) == original_project
    assert await timelines.load_timeline(project_id=first.project_id, workspace_id=7) == original_timeline
    assert await media.list_assets(workspace_id=7, project_id=first.project_id) == original_assets
    checksums: list[list[str]] = []
    for result in (first, second):
        project = await projects.get_project(result.project_id, workspace_id=7)
        assert project is not None and project.workspace_id == 7
        timeline = await timelines.load_timeline(project_id=result.project_id, workspace_id=7)
        assert timeline is not None and timeline.project_id == result.project_id
        assert Timeline.from_dict(timeline.model_dump(mode="json")) == timeline
        assert len(timeline.segments) == 2
        assert len({segment.scene_id for segment in timeline.segments}) == 2
        assert len({segment.asset_id for segment in timeline.segments}) == 2
        assert [segment.timeline_start_seconds for segment in timeline.segments] == [0.0, 2.0]
        assert sum(segment.duration_seconds for segment in timeline.segments) == 4.0
        assets: list[MediaAsset] = []
        for segment, color in zip(timeline.segments, ((32, 48, 80), (24, 192, 208)), strict=True):
            asset = await media.get_asset(segment.asset_id, 7)
            assert asset is not None and asset.project_id == project.id
            assert asset.workspace_id == 7 and asset.media_type is MediaType.IMAGE
            assert asset.id in result.asset_id_map.values()
            assert await media.get_asset(asset.id, 8) is None
            assert asset.metadata["license"] == "CC0-1.0"
            assert asset.metadata["provenance"] == "synthetic"
            assert asset.metadata["generator"] == "offline-demo"
            assert asset.source_url is None
            assert asset.storage_key is not None
            with BytesIO((tmp_path / asset.storage_key).read_bytes()) as buffer, Image.open(buffer) as image:
                assert image.format == "PNG"
                assert image.getpixel((0, 0)) == color
            assert MediaAsset.from_dict(asset.model_dump(mode="json")) == asset
            assets.append(asset)
        assert [asset.origin for asset in assets] == [MediaOrigin.GENERATED, MediaOrigin.UPLOADED]
        assert assets[1].metadata["example_role"] == "uploaded-example"
        assert assets[1].metadata["contains_private_media"] is False
        checksums.append([str(asset.metadata["checksum"]) for asset in assets])
        plan = await compile_timeline_to_render_plan(
            timeline, workspace_id=7, asset_resolver=media,
            output_spec=OutputSpec.short_vertical(), encoding_profile=EncodingProfile.preview(),
        )
        assert [segment.source for segment in plan.segments] == [asset.storage_key for asset in assets]
        assert result.run.project_id == project.id
        assert result.run.current_stage == "TIMELINE_REVIEW" and result.run.status == "paused"
    assert checksums[0] == checksums[1]
    assert checksums[0][0] != checksums[0][1]
    assert set(first.asset_id_map.values()).isdisjoint(second.asset_id_map.values())


@pytest.mark.asyncio
async def test_seed_does_not_create_run_when_timeline_save_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    media = MediaAssetService(LocalStorageBackend(str(tmp_path)), InMemoryMediaAssetStorage())
    runs = RunService(InMemoryRunStorage())
    timelines = TimelineService()

    async def fail_save(*, project_id: int, workspace_id: int, timeline: Timeline, expected_revision: int) -> Timeline:
        raise ValidationError("forced timeline storage failure")

    monkeypatch.setattr(timelines, "save_timeline", fail_save)
    with pytest.raises(ValidationError):
        await seed_demo_short(
            workspace_id=7, project_service=ProjectService(InMemoryProjectStorage()),
            media_asset_service=media, timeline_service=timelines, run_service=runs,
        )
    assert await runs.list_runs_by_workspace(7) == []
