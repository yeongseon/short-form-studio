"""SF-48: applier for the shared validated EditorCommand boundary.

apply_editor_command validates base revision, references, workspace access, and
source bounds, then rebuilds a NEW Timeline atomically (the input is never
mutated). Persistence/optimistic-concurrency stays in TimelineService.save.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError, VersionConflictError
from creator_domain.models import (
    DeleteSegmentCommand,
    MoveSegmentCommand,
    ReplaceAssetCommand,
    ResizeSegmentCommand,
    SetAudioCommand,
    SetTransitionCommand,
    SplitSegmentCommand,
    SwitchOutputCommand,
    Timeline,
    TrimSegmentCommand,
)
from creator_service.editor_command_applier import (
    EditorAssetRef,
    apply_editor_command,
)


class _FakeAssetLookup:
    def __init__(self, assets: dict[int, EditorAssetRef]) -> None:
        self._assets = assets

    async def get_asset_for_editor(
        self, asset_id: int, workspace_id: int
    ) -> EditorAssetRef | None:
        return self._assets.get(asset_id)


def _ref(
    asset_id: int,
    *,
    project_id: int = 1,
    media_type: str = "VIDEO",
    duration_seconds: float = 30.0,
) -> EditorAssetRef:
    return EditorAssetRef(
        id=asset_id,
        project_id=project_id,
        media_type=media_type,
        duration_seconds=duration_seconds,
    )


def _timeline() -> Timeline:
    return Timeline.model_validate(
        {
            "id": "tl-1",
            "project_id": 1,
            "revision": 3,
            "segments": [
                {
                    "id": "s1",
                    "scene_id": "scene-1",
                    "asset_id": 10,
                    "timeline_start_seconds": 0.0,
                    "duration_seconds": 4.0,
                    "trim_start_seconds": 0.0,
                    "trim_end_seconds": 4.0,
                },
                {
                    "id": "s2",
                    "scene_id": "scene-1",
                    "asset_id": 11,
                    "timeline_start_seconds": 4.0,
                    "duration_seconds": 3.0,
                },
            ],
        }
    )


def _lookup() -> _FakeAssetLookup:
    return _FakeAssetLookup({10: _ref(10), 11: _ref(11)})


async def _apply(command: object, *, base_revision: int = 3, lookup: _FakeAssetLookup | None = None) -> Timeline:
    return await apply_editor_command(
        _timeline(),
        command,  # type: ignore[arg-type]
        workspace_id=1,
        base_revision=base_revision,
        asset_lookup=lookup or _lookup(),
    )


@pytest.mark.asyncio
async def test_trim_updates_bounds_without_changing_revision() -> None:
    result = await _apply(
        TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0)
    )
    seg = next(s for s in result.segments if s.id == "s1")
    assert seg.trim_start_seconds == 1.0
    assert seg.trim_end_seconds == 3.0
    assert result.revision == 3


@pytest.mark.asyncio
async def test_trim_rejects_unknown_segment() -> None:
    with pytest.raises(ValidationError):
        await _apply(TrimSegmentCommand(segment_id="nope", trim_start_seconds=0.0, trim_end_seconds=1.0))


@pytest.mark.asyncio
async def test_trim_rejects_beyond_source_duration() -> None:
    lookup = _FakeAssetLookup({10: _ref(10, duration_seconds=3.0), 11: _ref(11)})
    with pytest.raises(ValidationError):
        await _apply(
            TrimSegmentCommand(segment_id="s1", trim_start_seconds=0.0, trim_end_seconds=5.0),
            lookup=lookup,
        )


@pytest.mark.asyncio
async def test_split_creates_two_segments() -> None:
    result = await _apply(SplitSegmentCommand(segment_id="s1", at_seconds=2.0))
    ids = [s.id for s in result.segments]
    assert len(result.segments) == 3
    assert any(i.startswith("s1") for i in ids)


@pytest.mark.asyncio
async def test_split_rejects_boundary() -> None:
    with pytest.raises(ValidationError):
        await _apply(SplitSegmentCommand(segment_id="s1", at_seconds=0.0))


@pytest.mark.asyncio
async def test_delete_ripple_shifts_following() -> None:
    result = await _apply(DeleteSegmentCommand(segment_id="s1", policy="ripple"))
    assert [s.id for s in result.segments] == ["s2"]
    assert result.segments[0].timeline_start_seconds == 0.0


@pytest.mark.asyncio
async def test_delete_gap_keeps_positions() -> None:
    result = await _apply(DeleteSegmentCommand(segment_id="s1", policy="gap"))
    assert result.segments[0].timeline_start_seconds == 4.0


@pytest.mark.asyncio
async def test_replace_asset_swaps_reference() -> None:
    lookup = _FakeAssetLookup({10: _ref(10), 11: _ref(11), 20: _ref(20, media_type="VIDEO")})
    result = await _apply(ReplaceAssetCommand(segment_id="s1", asset_id=20), lookup=lookup)
    assert next(s for s in result.segments if s.id == "s1").asset_id == 20


@pytest.mark.asyncio
async def test_replace_rejects_missing_asset() -> None:
    with pytest.raises(ValidationError):
        await _apply(ReplaceAssetCommand(segment_id="s1", asset_id=404))


@pytest.mark.asyncio
async def test_replace_rejects_cross_project_asset() -> None:
    lookup = _FakeAssetLookup({10: _ref(10), 11: _ref(11), 20: _ref(20, project_id=2)})
    with pytest.raises(ValidationError):
        await _apply(ReplaceAssetCommand(segment_id="s1", asset_id=20), lookup=lookup)


@pytest.mark.asyncio
async def test_replace_rejects_incompatible_kind() -> None:
    lookup = _FakeAssetLookup({10: _ref(10, media_type="VIDEO"), 11: _ref(11), 20: _ref(20, media_type="AUDIO")})
    with pytest.raises(ValidationError):
        await _apply(ReplaceAssetCommand(segment_id="s1", asset_id=20), lookup=lookup)


@pytest.mark.asyncio
async def test_move_reorders_and_resequences() -> None:
    result = await _apply(MoveSegmentCommand(segment_id="s1", target_index=1))
    assert [s.id for s in result.segments] == ["s2", "s1"]
    assert [s.timeline_start_seconds for s in result.segments] == [0.0, 3.0]


@pytest.mark.asyncio
async def test_move_rejects_out_of_range_index() -> None:
    with pytest.raises(ValidationError):
        await _apply(MoveSegmentCommand(segment_id="s1", target_index=5))


@pytest.mark.asyncio
async def test_resize_updates_duration_and_ripples() -> None:
    result = await _apply(ResizeSegmentCommand(segment_id="s1", duration_seconds=6.0))
    assert next(s for s in result.segments if s.id == "s1").duration_seconds == 6.0
    assert next(s for s in result.segments if s.id == "s2").timeline_start_seconds == 6.0


@pytest.mark.asyncio
async def test_resize_rejects_beyond_source() -> None:
    lookup = _FakeAssetLookup({10: _ref(10, duration_seconds=5.0), 11: _ref(11)})
    with pytest.raises(ValidationError):
        await _apply(ResizeSegmentCommand(segment_id="s1", duration_seconds=10.0), lookup=lookup)


@pytest.mark.asyncio
async def test_set_transition_applies() -> None:
    result = await _apply(SetTransitionCommand(segment_id="s2", transition="fade"))
    assert next(s for s in result.segments if s.id == "s2").transition == "fade"


@pytest.mark.asyncio
async def test_set_transition_rejects_unsupported_duration() -> None:
    # Timeline has no transition-duration field; accepting a duration would
    # silently drop it, so it must be rejected until the domain supports it.
    with pytest.raises(ValidationError):
        await _apply(
            SetTransitionCommand(segment_id="s2", transition="fade", duration_seconds=0.5)
        )


@pytest.mark.asyncio
async def test_replace_clamps_duration_when_new_source_shorter_without_trim_end() -> None:
    # s2 has no trim_end and duration 3; replacing its 30s source with a 2s one
    # must clamp the visible duration to fit the new source.
    lookup = _FakeAssetLookup(
        {10: _ref(10), 11: _ref(11), 21: _ref(21, media_type="VIDEO", duration_seconds=2.0)}
    )
    result = await _apply(ReplaceAssetCommand(segment_id="s2", asset_id=21), lookup=lookup)
    seg = next(s for s in result.segments if s.id.startswith("s2"))
    assert seg.duration_seconds <= 2.0 + 1e-6


@pytest.mark.asyncio
async def test_set_style_typed_but_not_applicable() -> None:
    from creator_domain.models import SetStyleCommand

    with pytest.raises(ValidationError):
        await _apply(SetStyleCommand(style="cinematic"))


@pytest.mark.asyncio
async def test_stale_base_revision_raises_before_mutation() -> None:
    with pytest.raises(VersionConflictError):
        await _apply(
            TrimSegmentCommand(segment_id="s1", trim_start_seconds=0.0, trim_end_seconds=1.0),
            base_revision=2,
        )


@pytest.mark.asyncio
async def test_output_style_audio_typed_but_not_applicable() -> None:
    for command in (
        SwitchOutputCommand(preset="short_square"),
        SetAudioCommand(music_volume=0.3),
    ):
        with pytest.raises(ValidationError):
            await _apply(command)


@pytest.mark.asyncio
async def test_no_partial_mutation_on_failure() -> None:
    original = _timeline()
    snapshot = original.model_dump(mode="json")
    with pytest.raises(ValidationError):
        await apply_editor_command(
            original,
            TrimSegmentCommand(segment_id="nope", trim_start_seconds=0.0, trim_end_seconds=1.0),
            workspace_id=1,
            base_revision=3,
            asset_lookup=_lookup(),
        )
    assert original.model_dump(mode="json") == snapshot


@pytest.mark.asyncio
async def test_returns_new_timeline_instance() -> None:
    original = _timeline()
    result = await apply_editor_command(
        original,
        TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0),
        workspace_id=1,
        base_revision=3,
        asset_lookup=_lookup(),
    )
    assert result is not original
