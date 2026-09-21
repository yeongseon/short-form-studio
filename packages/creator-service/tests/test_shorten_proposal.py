"""SF-58: deterministic AI shorten command builder.

build_shorten_proposal produces a valid CommandProposal (SF-55) that shortens a
timeline toward a target duration using ONLY existing timing/deletion commands.
The strategy is a prefix-preserving tail cut: keep the opening segments intact,
ripple-delete every segment after the target cut point (so the timeline stays
contiguous), and trim the boundary segment's tail so the retained content lands
on the target within tolerance. Source bounds are preserved (trims only reduce a
segment's window, never extend past its source). Unsupported requests — a
non-positive target, a timeline already within target, or a target unreachable
without dropping all content — raise a typed ValidationError. The proposal flows
unchanged through SF-56 apply and SF-57 diff, so cuts are explained and Apply/Undo
behave exactly as for any accepted batch.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    DeleteSegmentCommand,
    Timeline,
    TrimSegmentCommand,
)
from creator_service.command_proposal import CommandProposal
from creator_service.editor_command_applier import EditorAssetRef
from creator_service.editor_history import EditorHistory
from creator_service.proposal_diff import compute_proposal_diff
from creator_service.shorten_proposal import build_shorten_proposal
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
    start: float,
    duration: float,
    asset_id: int,
    *,
    trim_start: float = 0.0,
) -> dict[str, object]:
    return {
        "id": seg_id,
        "scene_id": "scene-1",
        "asset_id": asset_id,
        "timeline_start_seconds": start,
        "duration_seconds": duration,
        "trim_start_seconds": trim_start,
        "trim_end_seconds": trim_start + duration,
    }


def _timeline(segments: list[dict[str, object]], *, revision: int = 3) -> Timeline:
    return Timeline.model_validate(
        {"id": "tl-1", "project_id": 1, "revision": revision, "segments": segments}
    )


def _history(
    segments: list[dict[str, object]],
    assets: dict[int, EditorAssetRef] | None = None,
    *,
    revision: int = 3,
) -> EditorHistory:
    lookup = _FakeAssetLookup(
        assets or {10: _video(10), 11: _video(11), 12: _video(12), 13: _video(13)}
    )
    return EditorHistory(_timeline(segments, revision=revision), workspace_id=1, asset_lookup=lookup)


# A 40s timeline of four 10s segments: [0,10) [10,20) [20,30) [30,40).
def _forty_second_history() -> EditorHistory:
    return _history(
        [
            _seg("s1", 0.0, 10.0, 10),
            _seg("s2", 10.0, 10.0, 11),
            _seg("s3", 20.0, 10.0, 12),
            _seg("s4", 30.0, 10.0, 13),
        ]
    )


@pytest.mark.asyncio
async def test_shortens_to_target_within_tolerance() -> None:
    h = _forty_second_history()
    proposal = await build_shorten_proposal(h, target_seconds=25.0, tolerance_seconds=0.5)
    assert isinstance(proposal, CommandProposal)
    assert proposal.base_revision == 3
    diff = await compute_proposal_diff(h, proposal)
    assert abs(diff.total_duration_after - 25.0) <= 0.5
    assert diff.total_duration_before == 40.0


@pytest.mark.asyncio
async def test_ripple_deletes_tail_and_trims_boundary_segment() -> None:
    # target 25 falls inside s3 [20,30); keep s1,s2, trim s3 to end at 25, delete s4.
    h = _forty_second_history()
    proposal = await build_shorten_proposal(h, target_seconds=25.0, tolerance_seconds=0.5)
    deletes = [c for c in proposal.commands if isinstance(c, DeleteSegmentCommand)]
    trims = [c for c in proposal.commands if isinstance(c, TrimSegmentCommand)]
    assert {c.segment_id for c in deletes} == {"s4"}
    assert all(c.policy == "ripple" for c in deletes)
    assert [c.segment_id for c in trims] == ["s3"]
    assert trims[0].trim_end_seconds == pytest.approx(5.0)  # 5s of the 10s window kept


@pytest.mark.asyncio
async def test_boundary_hit_deletes_only_no_trim() -> None:
    # target exactly on the s2/s3 boundary (20.0): delete s3 and s4, no trim needed.
    h = _forty_second_history()
    proposal = await build_shorten_proposal(h, target_seconds=20.0, tolerance_seconds=0.5)
    assert all(isinstance(c, DeleteSegmentCommand) for c in proposal.commands)
    assert {c.segment_id for c in proposal.commands} == {"s3", "s4"}
    diff = await compute_proposal_diff(h, proposal)
    assert diff.total_duration_after == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_rejects_already_short_enough() -> None:
    h = _forty_second_history()
    with pytest.raises(ValidationError, match="already within"):
        await build_shorten_proposal(h, target_seconds=45.0, tolerance_seconds=0.5)


@pytest.mark.asyncio
async def test_rejects_non_positive_target() -> None:
    h = _forty_second_history()
    with pytest.raises(ValidationError, match="target"):
        await build_shorten_proposal(h, target_seconds=0.0, tolerance_seconds=0.5)


@pytest.mark.asyncio
async def test_rejects_negative_tolerance() -> None:
    h = _forty_second_history()
    with pytest.raises(ValidationError, match="tolerance"):
        await build_shorten_proposal(h, target_seconds=25.0, tolerance_seconds=-1.0)


@pytest.mark.asyncio
async def test_rejects_target_below_minimum_first_segment() -> None:
    # A target below the technical positive-duration floor cannot yield a valid
    # trim of the retained opening segment, so it is unreachable without dropping
    # all content (prefix-preserving keeps s1).
    h = _history([_seg("s1", 0.0, 10.0, 10)])
    with pytest.raises(ValidationError, match="cannot reach|without dropping"):
        await build_shorten_proposal(h, target_seconds=0.0005, tolerance_seconds=0.0)


@pytest.mark.asyncio
async def test_respects_existing_trim_start_when_trimming_boundary() -> None:
    # s3 already trimmed to start at 4.0 of its source; shortening must set
    # trim_end relative to that trim_start, never resetting the source offset.
    h = _history(
        [
            _seg("s1", 0.0, 10.0, 10),
            _seg("s2", 10.0, 10.0, 11),
            _seg("s3", 20.0, 10.0, 12, trim_start=4.0),
            _seg("s4", 30.0, 10.0, 13),
        ]
    )
    proposal = await build_shorten_proposal(h, target_seconds=25.0, tolerance_seconds=0.5)
    trims = [c for c in proposal.commands if isinstance(c, TrimSegmentCommand)]
    assert trims[0].segment_id == "s3"
    assert trims[0].trim_start_seconds == pytest.approx(4.0)
    # keep 5s of s3 -> trim_end = 4.0 + 5.0 = 9.0 (within the 60s source bound)
    assert trims[0].trim_end_seconds == pytest.approx(9.0)


@pytest.mark.asyncio
async def test_preview_diff_explains_cuts_and_apply_undo_round_trip() -> None:
    h = _forty_second_history()
    original = h.present.model_dump(mode="json")
    proposal = await build_shorten_proposal(h, target_seconds=25.0, tolerance_seconds=0.5)

    diff = await compute_proposal_diff(h, proposal)
    assert [s.id for s in diff.removed] == ["s4"]
    assert [m.segment_id for m in diff.modified] == ["s3"]

    applied = await apply_ai_proposal(h, proposal)
    assert applied.total_duration_seconds == pytest.approx(25.0, abs=0.5)
    assert h.generation == 4

    reverted = await h.undo()
    assert reverted.model_dump(mode="json") == original
    assert h.generation == 3


@pytest.mark.asyncio
async def test_builder_does_not_mutate_history() -> None:
    h = _forty_second_history()
    before = h.present.model_dump(mode="json")
    await build_shorten_proposal(h, target_seconds=25.0, tolerance_seconds=0.5)
    assert h.present.model_dump(mode="json") == before
    assert h.generation == 3
    assert h.can_undo is False


def _gap_history() -> EditorHistory:
    # A timeline with a gap [10,12): s1 [0,10), s2 [12,20). total = 20.
    return _history(
        [
            _seg("s1", 0.0, 10.0, 10),
            _seg("s2", 12.0, 8.0, 11),
        ]
    )


@pytest.mark.asyncio
async def test_target_in_gap_within_tolerance_deletes_later_only() -> None:
    # target 11 falls in the gap [10,12); the closest earlier end is 10 (s1),
    # within tolerance 1.5, so delete s2 and land at 10 without a trim.
    h = _gap_history()
    proposal = await build_shorten_proposal(h, target_seconds=11.0, tolerance_seconds=1.5)
    assert all(isinstance(c, DeleteSegmentCommand) for c in proposal.commands)
    assert {c.segment_id for c in proposal.commands} == {"s2"}
    diff = await compute_proposal_diff(h, proposal)
    assert diff.total_duration_after == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_target_in_gap_outside_tolerance_is_unreachable() -> None:
    # target 11 in the gap, closest earlier end 10, undershoot 1.0 > tolerance 0.25.
    h = _gap_history()
    with pytest.raises(ValidationError, match="available cut points|cannot reach"):
        await build_shorten_proposal(h, target_seconds=11.0, tolerance_seconds=0.25)


@pytest.mark.asyncio
async def test_rejects_non_finite_target_and_tolerance() -> None:
    h = _forty_second_history()
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValidationError, match="finite"):
            await build_shorten_proposal(h, target_seconds=bad, tolerance_seconds=0.5)
        with pytest.raises(ValidationError, match="finite"):
            await build_shorten_proposal(h, target_seconds=25.0, tolerance_seconds=bad)
