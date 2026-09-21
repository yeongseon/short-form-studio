"""SF-56: validate AI command proposals through the shared editor boundary.

apply_ai_proposal treats a CommandProposal (SF-55) as untrusted: it revalidates
the proposal's base_revision against the CURRENT timeline at Apply (stale ->
VersionConflictError) and then applies the batch atomically through
EditorHistory (which validates every command's type/target/ownership/timings via
the shared applier). A rejected proposal leaves the timeline unmutated and does
not enter history — nothing is applied before validation passes.
"""

from __future__ import annotations

import asyncio

import pytest
from creator_domain.exceptions import ValidationError, VersionConflictError
from creator_domain.models import Timeline
from creator_service.command_proposal import CommandProposal
from creator_service.editor_command_applier import EditorAssetRef
from creator_service.editor_history import EditorHistory
from creator_service.validate_ai_proposal import apply_ai_proposal


class _FakeAssetLookup:
    def __init__(self, assets: dict[int, EditorAssetRef]) -> None:
        self._assets = assets

    async def get_asset_for_editor(
        self, asset_id: int, workspace_id: int
    ) -> EditorAssetRef | None:
        return self._assets.get(asset_id)


def _ref(asset_id: int, *, project_id: int = 1, duration_seconds: float = 30.0) -> EditorAssetRef:
    return EditorAssetRef(
        id=asset_id, project_id=project_id, media_type="VIDEO", duration_seconds=duration_seconds
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


def _history(assets: dict[int, EditorAssetRef] | None = None) -> EditorHistory:
    lookup = _FakeAssetLookup(assets or {10: _ref(10), 11: _ref(11)})
    return EditorHistory(_timeline(), workspace_id=1, asset_lookup=lookup)


def _proposal(commands: list[dict[str, object]], base_revision: int = 3) -> CommandProposal:
    return CommandProposal.model_validate({"base_revision": base_revision, "commands": commands})


@pytest.mark.asyncio
async def test_applies_a_valid_proposal_atomically() -> None:
    h = _history()
    proposal = _proposal(
        [
            {"type": "trimSegment", "segment_id": "s1", "trim_start_seconds": 1.0, "trim_end_seconds": 3.0},
            {"type": "deleteSegment", "segment_id": "s2", "policy": "ripple"},
        ]
    )
    result = await apply_ai_proposal(h, proposal)
    assert [s.id for s in result.segments] == ["s1"]
    assert h.can_undo is True


@pytest.mark.asyncio
async def test_rejects_a_stale_proposal_without_mutating() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    proposal = _proposal(
        [{"type": "deleteSegment", "segment_id": "s1"}], base_revision=2
    )
    with pytest.raises(VersionConflictError):
        await apply_ai_proposal(h, proposal)
    assert h.can_undo is False
    assert h.present.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_rejects_a_hallucinated_segment_id_without_mutating() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    proposal = _proposal([{"type": "deleteSegment", "segment_id": "ghost"}])
    with pytest.raises(ValidationError):
        await apply_ai_proposal(h, proposal)
    assert h.can_undo is False
    assert h.present.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_rejects_a_cross_project_replacement_asset() -> None:
    h = _history({10: _ref(10), 11: _ref(11), 20: _ref(20, project_id=2)})
    before = h.present.model_dump(mode="json")
    proposal = _proposal([{"type": "replaceAsset", "segment_id": "s1", "asset_id": 20}])
    with pytest.raises(ValidationError):
        await apply_ai_proposal(h, proposal)
    assert h.present.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_rejects_a_cross_workspace_asset_as_unavailable() -> None:
    # asset 20 is not resolvable in workspace 1 (lookup returns None)
    h = _history({10: _ref(10), 11: _ref(11)})
    proposal = _proposal([{"type": "replaceAsset", "segment_id": "s1", "asset_id": 20}])
    with pytest.raises(ValidationError):
        await apply_ai_proposal(h, proposal)


@pytest.mark.asyncio
async def test_rejects_invalid_timing_trim_beyond_source() -> None:
    h = _history({10: _ref(10, duration_seconds=3.0), 11: _ref(11)})
    before = h.present.model_dump(mode="json")
    proposal = _proposal(
        [{"type": "trimSegment", "segment_id": "s1", "trim_start_seconds": 0.0, "trim_end_seconds": 5.0}]
    )
    with pytest.raises(ValidationError):
        await apply_ai_proposal(h, proposal)
    assert h.present.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_a_partially_invalid_batch_lands_nothing() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    proposal = _proposal(
        [
            {"type": "trimSegment", "segment_id": "s1", "trim_start_seconds": 1.0, "trim_end_seconds": 3.0},
            {"type": "deleteSegment", "segment_id": "ghost"},
        ]
    )
    with pytest.raises(ValidationError):
        await apply_ai_proposal(h, proposal)
    assert h.can_undo is False
    assert h.present.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_revalidates_against_moved_current_revision_not_proposal_claim() -> None:
    # A proposal generated against an older revision is stale even though its own
    # base_revision field is internally consistent.
    h = _history()
    proposal = _proposal([{"type": "deleteSegment", "segment_id": "s1"}], base_revision=1)
    with pytest.raises(VersionConflictError):
        await apply_ai_proposal(h, proposal)


@pytest.mark.asyncio
async def test_second_proposal_with_same_base_revision_is_stale_after_a_mutation() -> None:
    # Applying proposal A advances the history's edit generation (3 -> 4), so a
    # second proposal B still claiming base_revision 3 is stale and must be
    # rejected without mutating the timeline further. Timeline.revision itself
    # stays the persistence token (unchanged in-memory).
    h = _history()
    proposal_a = _proposal(
        [{"type": "deleteSegment", "segment_id": "s2", "policy": "ripple"}], base_revision=3
    )
    await apply_ai_proposal(h, proposal_a)
    after_a = h.present.model_dump(mode="json")
    assert h.generation == 4

    proposal_b = _proposal(
        [{"type": "deleteSegment", "segment_id": "s1", "policy": "ripple"}], base_revision=3
    )
    with pytest.raises(VersionConflictError):
        await apply_ai_proposal(h, proposal_b)
    assert h.present.model_dump(mode="json") == after_a


@pytest.mark.asyncio
async def test_concurrent_same_generation_proposals_apply_exactly_once() -> None:
    # Two proposals built against the same generation applied concurrently: the
    # check-and-apply is one critical section, so exactly one succeeds and the
    # other is rejected as stale (no double-apply race).
    h = _history()
    proposal_a = _proposal(
        [{"type": "deleteSegment", "segment_id": "s2", "policy": "ripple"}], base_revision=3
    )
    proposal_b = _proposal(
        [{"type": "deleteSegment", "segment_id": "s1", "policy": "ripple"}], base_revision=3
    )
    results = await asyncio.gather(
        apply_ai_proposal(h, proposal_a),
        apply_ai_proposal(h, proposal_b),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, Timeline)]
    conflicts = [r for r in results if isinstance(r, VersionConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert h.generation == 4
