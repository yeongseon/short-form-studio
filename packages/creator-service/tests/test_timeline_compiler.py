"""SF-29: compile a saved Timeline revision deterministically into a RenderPlan.

Each MediaSegment's asset_id is resolved to an owned MediaAsset (same project +
workspace), mapped to a RenderSegment (kind from media_type, source from
storage_key), with source-bound-validated trims, preserved timing/transitions.
Asset ownership, source bounds, and supported transitions are validated.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    EncodingProfile,
    MediaAsset,
    MediaOrigin,
    MediaType,
    OutputSpec,
    RenderPlan,
    RenderSegmentKind,
    Timeline,
)
from creator_service.timeline_compiler import compile_timeline_to_render_plan


class _FakeAssetResolver:
    def __init__(self, assets: dict[int, MediaAsset]) -> None:
        self._assets = assets

    async def get_asset(self, asset_id: int, workspace_id: int) -> MediaAsset | None:
        asset = self._assets.get(asset_id)
        if asset is None or asset.workspace_id != workspace_id:
            return None
        return asset


def _asset(
    asset_id: int,
    *,
    workspace_id: int = 1,
    project_id: int | None = 1,
    media_type: MediaType = MediaType.IMAGE,
    storage_key: str = "workspaces/1/assets/a.png",
    duration_seconds: float | None = None,
) -> MediaAsset:
    return MediaAsset(
        id=asset_id,
        workspace_id=workspace_id,
        project_id=project_id,
        media_type=media_type,
        origin=MediaOrigin.UPLOADED,
        storage_key=storage_key,
        duration_seconds=duration_seconds,
        created_at=datetime.now(timezone.utc),
    )


def _timeline(segments: list[dict[str, object]], project_id: int = 1) -> Timeline:
    return Timeline.model_validate(
        {"id": "tl-1", "project_id": project_id, "revision": 3, "segments": segments}
    )


def _seg(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "seg-1",
        "scene_id": "scene-1",
        "asset_id": 10,
        "timeline_start_seconds": 0.0,
        "duration_seconds": 4.0,
    }
    payload.update(overrides)
    return payload


async def _compile(timeline: Timeline, resolver: _FakeAssetResolver, **kw: object) -> RenderPlan:
    return await compile_timeline_to_render_plan(
        timeline,
        workspace_id=kw.get("workspace_id", 1),
        output_spec=kw.get("output_spec", OutputSpec.short_vertical()),
        encoding_profile=kw.get("encoding_profile", EncodingProfile.preview()),
        asset_resolver=resolver,
    )


@pytest.mark.asyncio
async def test_compiles_image_segment_to_render_segment() -> None:
    resolver = _FakeAssetResolver({10: _asset(10, media_type=MediaType.IMAGE)})
    plan = await _compile(_timeline([_seg()]), resolver)
    assert isinstance(plan, RenderPlan)
    assert len(plan.segments) == 1
    seg = plan.segments[0]
    assert seg.kind is RenderSegmentKind.IMAGE
    assert seg.source == "workspaces/1/assets/a.png"
    assert seg.timeline_start_seconds == 0.0
    assert seg.duration_seconds == 4.0
    assert plan.output_spec == OutputSpec.short_vertical()
    assert plan.encoding_profile == EncodingProfile.preview()


@pytest.mark.asyncio
async def test_maps_video_asset_to_video_kind() -> None:
    resolver = _FakeAssetResolver(
        {10: _asset(10, media_type=MediaType.VIDEO, storage_key="v.mp4", duration_seconds=30.0)}
    )
    plan = await _compile(_timeline([_seg()]), resolver)
    assert plan.segments[0].kind is RenderSegmentKind.VIDEO


@pytest.mark.asyncio
async def test_deterministic_ordering_by_timeline_start() -> None:
    resolver = _FakeAssetResolver(
        {10: _asset(10), 11: _asset(11, storage_key="b.png")}
    )
    tl = _timeline(
        [
            _seg(id="s2", asset_id=11, timeline_start_seconds=4.0, duration_seconds=2.0),
            _seg(id="s1", asset_id=10, timeline_start_seconds=0.0, duration_seconds=4.0),
        ]
    )
    plan = await _compile(tl, resolver)
    assert [s.timeline_start_seconds for s in plan.segments] == [0.0, 4.0]
    # deterministic: recompiling yields identical serialization
    plan2 = await _compile(tl, resolver)
    assert plan.to_json() == plan2.to_json()


@pytest.mark.asyncio
async def test_preserves_transition() -> None:
    resolver = _FakeAssetResolver({10: _asset(10)})
    plan = await _compile(_timeline([_seg(transition="fade")]), resolver)
    assert plan.segments[0].transition == "fade"


@pytest.mark.asyncio
async def test_rejects_unsupported_transition() -> None:
    resolver = _FakeAssetResolver({10: _asset(10)})
    with pytest.raises(ValidationError):
        await _compile(_timeline([_seg(transition="explode")]), resolver)


@pytest.mark.asyncio
async def test_rejects_asset_from_other_project() -> None:
    resolver = _FakeAssetResolver({10: _asset(10, project_id=2)})
    with pytest.raises(ValidationError):
        await _compile(_timeline([_seg()]), resolver)


@pytest.mark.asyncio
async def test_rejects_asset_from_other_workspace_as_missing() -> None:
    resolver = _FakeAssetResolver({10: _asset(10, workspace_id=2)})
    with pytest.raises(ValidationError):
        await _compile(_timeline([_seg()]), resolver)


@pytest.mark.asyncio
async def test_rejects_missing_asset() -> None:
    resolver = _FakeAssetResolver({})
    with pytest.raises(ValidationError):
        await _compile(_timeline([_seg(asset_id=404)]), resolver)


@pytest.mark.asyncio
async def test_rejects_video_trim_beyond_source_duration() -> None:
    resolver = _FakeAssetResolver(
        {10: _asset(10, media_type=MediaType.VIDEO, storage_key="v.mp4", duration_seconds=5.0)}
    )
    tl = _timeline([_seg(trim_start_seconds=1.0, trim_end_seconds=9.0)])
    with pytest.raises(ValidationError):
        await _compile(tl, resolver)


@pytest.mark.asyncio
async def test_allows_video_trim_within_source_duration() -> None:
    resolver = _FakeAssetResolver(
        {10: _asset(10, media_type=MediaType.VIDEO, storage_key="v.mp4", duration_seconds=30.0)}
    )
    tl = _timeline([_seg(trim_start_seconds=1.0, trim_end_seconds=3.0)])
    plan = await _compile(tl, resolver)
    assert plan.segments[0].trim_start_seconds == 1.0
    assert plan.segments[0].trim_end_seconds == 3.0


@pytest.mark.asyncio
async def test_rejects_video_implicit_end_beyond_source_duration() -> None:
    # trim_end omitted: renderer uses trim_start + duration_seconds, so a 10s
    # segment over a 5s source overruns even with no explicit trim.
    resolver = _FakeAssetResolver(
        {10: _asset(10, media_type=MediaType.VIDEO, storage_key="v.mp4", duration_seconds=5.0)}
    )
    tl = _timeline([_seg(timeline_start_seconds=0.0, duration_seconds=10.0)])
    with pytest.raises(ValidationError):
        await _compile(tl, resolver)


@pytest.mark.asyncio
async def test_rejects_asset_matching_project_but_other_workspace() -> None:
    # Defense in depth: resolver returns an asset whose workspace_id mismatches.
    resolver = _FakeAssetResolver({10: _asset(10, workspace_id=2, project_id=1)})

    class _LeakyResolver:
        async def get_asset(self, asset_id: int, workspace_id: int) -> MediaAsset | None:
            return resolver._assets.get(asset_id)

    with pytest.raises(ValidationError):
        await compile_timeline_to_render_plan(
            _timeline([_seg()]),
            workspace_id=1,
            output_spec=OutputSpec.short_vertical(),
            encoding_profile=EncodingProfile.preview(),
            asset_resolver=_LeakyResolver(),
        )


@pytest.mark.asyncio
async def test_rejects_asset_without_storage_key() -> None:
    resolver = _FakeAssetResolver({10: _asset(10, storage_key=None)})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        await _compile(_timeline([_seg()]), resolver)


@pytest.mark.asyncio
async def test_empty_timeline_compiles_to_empty_plan_or_rejects() -> None:
    # RenderPlan requires >=1 segment; an empty timeline must be rejected clearly.
    resolver = _FakeAssetResolver({})
    with pytest.raises(ValidationError):
        await _compile(_timeline([]), resolver)
