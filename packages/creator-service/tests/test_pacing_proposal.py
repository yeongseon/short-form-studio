"""SF-59: deterministic AI pacing command builder.

build_pacing_proposal turns "make the opening faster/slower" into a valid
CommandProposal (SF-55) using ONLY existing duration/transition commands, so it
flows unchanged through SF-56 apply and SF-57 diff. Pacing scales in-scope
segment durations by a factor via resizeSegment (whose ripple keeps the timeline
contiguous so nothing desyncs), optionally pairing a transition kind. Video
segments are clamped to their remaining source duration so source bounds are
respected; a slower video already at its source max is skipped rather than
emitting a no-op resize. Scope is by scene id: unrelated scenes keep their
content (asset/duration/trim/transition), shifting only in placement from the
ripple — the intended pacing behavior. Unsupported requests (a near-1.0 or
non-positive/non-finite factor, unknown scene ids, or a scope that yields no
actual change) raise a typed ValidationError.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    ResizeSegmentCommand,
    SetTransitionCommand,
    Timeline,
)
from creator_service.command_proposal import CommandProposal
from creator_service.editor_command_applier import EditorAssetRef
from creator_service.editor_history import EditorHistory
from creator_service.pacing_proposal import build_pacing_proposal
from creator_service.proposal_diff import compute_proposal_diff
from creator_service.validate_ai_proposal import apply_ai_proposal


class _FakeAssetLookup:
    def __init__(self, assets: dict[int, EditorAssetRef]) -> None:
        self._assets = assets

    async def get_asset_for_editor(
        self, asset_id: int, workspace_id: int
    ) -> EditorAssetRef | None:
        return self._assets.get(asset_id)


def _video(asset_id: int, *, duration_seconds: float = 60.0) -> EditorAssetRef:
    return EditorAssetRef(
        id=asset_id, project_id=1, media_type="VIDEO", duration_seconds=duration_seconds
    )


def _seg(
    seg_id: str,
    scene_id: str,
    start: float,
    duration: float,
    asset_id: int,
    *,
    trim_start: float = 0.0,
    transition: str | None = None,
) -> dict[str, object]:
    return {
        "id": seg_id,
        "scene_id": scene_id,
        "asset_id": asset_id,
        "timeline_start_seconds": start,
        "duration_seconds": duration,
        "trim_start_seconds": trim_start,
        "trim_end_seconds": trim_start + duration,
        "transition": transition,
    }


def _timeline(segments: list[dict[str, object]], *, revision: int = 3) -> Timeline:
    return Timeline.model_validate(
        {"id": "tl-1", "project_id": 1, "revision": revision, "segments": segments}
    )


def _history(
    segments: list[dict[str, object]],
    assets: dict[int, EditorAssetRef] | None = None,
) -> EditorHistory:
    lookup = _FakeAssetLookup(
        assets or {10: _video(10), 11: _video(11), 12: _video(12), 13: _video(13)}
    )
    return EditorHistory(_timeline(segments), workspace_id=1, asset_lookup=lookup)


# Two scenes: opening scene-A [s1,s2], later scene-B [s3,s4], each segment 10s.
def _two_scene_history() -> EditorHistory:
    return _history(
        [
            _seg("s1", "scene-A", 0.0, 10.0, 10),
            _seg("s2", "scene-A", 10.0, 10.0, 11),
            _seg("s3", "scene-B", 20.0, 10.0, 12),
            _seg("s4", "scene-B", 30.0, 10.0, 13),
        ]
    )


@pytest.mark.asyncio
async def test_faster_pacing_shrinks_durations() -> None:
    h = _two_scene_history()
    proposal = await build_pacing_proposal(h, factor=0.5)
    assert isinstance(proposal, CommandProposal)
    assert proposal.base_revision == 3
    resizes = [c for c in proposal.commands if isinstance(c, ResizeSegmentCommand)]
    assert {c.segment_id for c in resizes} == {"s1", "s2", "s3", "s4"}
    assert all(c.duration_seconds == pytest.approx(5.0) for c in resizes)
    diff = await compute_proposal_diff(h, proposal)
    assert diff.total_duration_after == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_slower_pacing_grows_durations_within_source() -> None:
    h = _two_scene_history()
    proposal = await build_pacing_proposal(h, factor=1.5)
    resizes = [c for c in proposal.commands if isinstance(c, ResizeSegmentCommand)]
    assert all(c.duration_seconds == pytest.approx(15.0) for c in resizes)
    diff = await compute_proposal_diff(h, proposal)
    assert diff.total_duration_after == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_slower_pacing_clamps_video_to_remaining_source() -> None:
    # s1 sourced from a 12s asset, already 10s: 1.5x wants 15s but only 12s of
    # source remains, so the resize is clamped to 12s (best-effort within bounds).
    h = _history(
        [_seg("s1", "scene-A", 0.0, 10.0, 10)],
        assets={10: _video(10, duration_seconds=12.0)},
    )
    proposal = await build_pacing_proposal(h, factor=1.5)
    resize = next(c for c in proposal.commands if isinstance(c, ResizeSegmentCommand))
    assert resize.duration_seconds == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_slower_pacing_skips_segment_already_at_source_max() -> None:
    # s1 is already at its full 10s source; 1.5x cannot grow it, so it is skipped.
    # s2 has headroom (60s source) and is resized, so the proposal is non-empty.
    h = _history(
        [
            _seg("s1", "scene-A", 0.0, 10.0, 10),
            _seg("s2", "scene-A", 10.0, 10.0, 11),
        ],
        assets={10: _video(10, duration_seconds=10.0), 11: _video(11)},
    )
    proposal = await build_pacing_proposal(h, factor=1.5)
    resized_ids = {c.segment_id for c in proposal.commands if isinstance(c, ResizeSegmentCommand)}
    assert resized_ids == {"s2"}


@pytest.mark.asyncio
async def test_opening_only_scope_leaves_unrelated_scene_content_unchanged() -> None:
    h = _two_scene_history()
    proposal = await build_pacing_proposal(h, factor=0.5, scene_ids=["scene-A"])
    resized_ids = {c.segment_id for c in proposal.commands if isinstance(c, ResizeSegmentCommand)}
    assert resized_ids == {"s1", "s2"}

    diff = await compute_proposal_diff(h, proposal)
    # scene-B segments (s3, s4) are not resized; the ripple only shifts their
    # timeline_start_seconds. Assert their CONTENT fields are untouched — the only
    # reported change for them is placement, never asset/duration/trim/transition.
    assert diff.removed == []
    assert diff.added == []
    unrelated = {m.segment_id: m for m in diff.modified if m.segment_id in {"s3", "s4"}}
    assert set(unrelated) == {"s3", "s4"}
    for modified in unrelated.values():
        changed_fields = {c.field for c in modified.changes}
        assert changed_fields == {"timeline_start_seconds"}
    # the opening scene-A segments are the ones actually re-paced (duration change)
    paced = {m.segment_id: m for m in diff.modified if m.segment_id in {"s1", "s2"}}
    assert set(paced) == {"s1", "s2"}
    for modified in paced.values():
        assert "duration_seconds" in {c.field for c in modified.changes}


@pytest.mark.asyncio
async def test_pacing_can_pair_a_transition_kind() -> None:
    h = _two_scene_history()
    proposal = await build_pacing_proposal(h, factor=0.5, scene_ids=["scene-A"], transition="cut")
    transitions = [c for c in proposal.commands if isinstance(c, SetTransitionCommand)]
    assert {c.segment_id for c in transitions} == {"s1", "s2"}
    assert all(c.transition == "cut" and c.duration_seconds is None for c in transitions)


@pytest.mark.asyncio
async def test_transition_only_emitted_when_kind_changes() -> None:
    # s1 already has "cut"; a pacing request also setting "cut" must not emit a
    # redundant setTransition for s1 (only s2, which has no transition).
    h = _history(
        [
            _seg("s1", "scene-A", 0.0, 10.0, 10, transition="cut"),
            _seg("s2", "scene-A", 10.0, 10.0, 11),
        ]
    )
    proposal = await build_pacing_proposal(h, factor=0.5, transition="cut")
    transition_ids = {c.segment_id for c in proposal.commands if isinstance(c, SetTransitionCommand)}
    assert transition_ids == {"s2"}


@pytest.mark.asyncio
async def test_rejects_unknown_scene_id() -> None:
    h = _two_scene_history()
    with pytest.raises(ValidationError, match="scene"):
        await build_pacing_proposal(h, factor=0.5, scene_ids=["scene-A", "scene-Z"])


@pytest.mark.asyncio
async def test_rejects_factor_near_one() -> None:
    h = _two_scene_history()
    with pytest.raises(ValidationError, match="factor"):
        await build_pacing_proposal(h, factor=1.0)


@pytest.mark.asyncio
async def test_rejects_non_positive_and_non_finite_factor() -> None:
    h = _two_scene_history()
    for bad in (0.0, -0.5, float("nan"), float("inf")):
        with pytest.raises(ValidationError, match="factor"):
            await build_pacing_proposal(h, factor=bad)


@pytest.mark.asyncio
async def test_rejects_when_scope_yields_no_change() -> None:
    # Every scoped segment is already at its source max, so a slower factor
    # produces no resize and (no transition) no command at all.
    h = _history(
        [_seg("s1", "scene-A", 0.0, 10.0, 10)],
        assets={10: _video(10, duration_seconds=10.0)},
    )
    with pytest.raises(ValidationError, match="no pacing change|no segments"):
        await build_pacing_proposal(h, factor=1.5)


@pytest.mark.asyncio
async def test_preview_apply_undo_round_trip_and_no_mutation() -> None:
    h = _two_scene_history()
    original = h.present.model_dump(mode="json")
    proposal = await build_pacing_proposal(h, factor=0.5, scene_ids=["scene-A"])

    # builder is read-only
    assert h.present.model_dump(mode="json") == original
    assert h.generation == 3

    applied = await apply_ai_proposal(h, proposal)
    assert applied.total_duration_seconds == pytest.approx(30.0)
    assert h.generation == 4

    reverted = await h.undo()
    assert reverted.model_dump(mode="json") == original
    assert h.generation == 3
