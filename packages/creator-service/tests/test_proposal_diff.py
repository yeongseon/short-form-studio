"""SF-57: read-only before/after diff for an AI command proposal.

compute_proposal_diff previews what a CommandProposal (SF-55) would do to the
Timeline without mutating EditorHistory: it revalidates staleness against the
history's edit generation exactly like Apply (SF-56), folds the batch through the
shared applier on a captured copy, and returns a structural segment diff. A stale
or invalid proposal is rejected identically to Apply and leaves history untouched;
style/audio/output commands are not applicable to the Timeline and raise the same
ValidationError Apply would. Cancel is a pure no-op (compute + discard), and an
applied AI batch undoes as one step, matching a manual edit's undo.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError, VersionConflictError
from creator_domain.models import Timeline
from creator_service.command_proposal import CommandProposal
from creator_service.editor_command_applier import EditorAssetRef
from creator_service.editor_history import EditorHistory
from creator_service.proposal_diff import ProposalDiff, compute_proposal_diff
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
    lookup = _FakeAssetLookup(assets or {10: _ref(10), 11: _ref(11), 12: _ref(12)})
    return EditorHistory(_timeline(), workspace_id=1, asset_lookup=lookup)


def _proposal(commands: list[dict[str, object]], base_revision: int = 3) -> CommandProposal:
    return CommandProposal.model_validate({"base_revision": base_revision, "commands": commands})


@pytest.mark.asyncio
async def test_diff_reports_removed_and_modified_segments() -> None:
    h = _history()
    proposal = _proposal(
        [
            {"type": "trimSegment", "segment_id": "s1", "trim_start_seconds": 1.0, "trim_end_seconds": 3.0},
            {"type": "deleteSegment", "segment_id": "s2", "policy": "ripple"},
        ]
    )
    diff = await compute_proposal_diff(h, proposal)
    assert isinstance(diff, ProposalDiff)
    assert diff.base_revision == 3
    assert [s.id for s in diff.removed] == ["s2"]
    assert diff.added == []
    assert [m.segment_id for m in diff.modified] == ["s1"]
    changed = {c.field for c in diff.modified[0].changes}
    assert {"trim_start_seconds", "trim_end_seconds"} <= changed
    assert diff.total_duration_before == 7.0
    assert diff.total_duration_after == 2.0


@pytest.mark.asyncio
async def test_diff_reports_replaced_asset_as_modified() -> None:
    h = _history()
    proposal = _proposal([{"type": "replaceAsset", "segment_id": "s1", "asset_id": 12}])
    diff = await compute_proposal_diff(h, proposal)
    assert [m.segment_id for m in diff.modified] == ["s1"]
    change = next(c for c in diff.modified[0].changes if c.field == "asset_id")
    assert change.before == 10
    assert change.after == 12


@pytest.mark.asyncio
async def test_preview_does_not_mutate_history() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    proposal = _proposal([{"type": "deleteSegment", "segment_id": "s2", "policy": "ripple"}])
    await compute_proposal_diff(h, proposal)
    assert h.present.model_dump(mode="json") == before
    assert h.generation == 3
    assert h.can_undo is False
    assert h.can_redo is False


@pytest.mark.asyncio
async def test_preview_rejects_a_stale_proposal_without_mutating() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    proposal = _proposal([{"type": "deleteSegment", "segment_id": "s1"}], base_revision=2)
    with pytest.raises(VersionConflictError):
        await compute_proposal_diff(h, proposal)
    assert h.present.model_dump(mode="json") == before
    assert h.generation == 3


@pytest.mark.asyncio
async def test_preview_rejects_an_invalid_command_like_apply() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    proposal = _proposal([{"type": "deleteSegment", "segment_id": "ghost"}])
    with pytest.raises(ValidationError):
        await compute_proposal_diff(h, proposal)
    assert h.present.model_dump(mode="json") == before
    assert h.generation == 3


@pytest.mark.asyncio
async def test_preview_rejects_style_audio_output_commands_like_apply() -> None:
    # style/audio/output commands are not applicable to the Timeline; the applier
    # rejects them, so both preview and apply raise ValidationError on the whole
    # batch. Preview must never show a diff for a batch Apply would reject.
    for command in (
        {"type": "setStyle", "style": "cinematic"},
        {"type": "setAudio", "music_volume": 0.3},
        {"type": "switchOutput", "preset": "short_square"},
    ):
        h = _history()
        proposal = _proposal([command])
        with pytest.raises(ValidationError):
            await compute_proposal_diff(h, proposal)
        with pytest.raises(ValidationError):
            await apply_ai_proposal(h, proposal)
        assert h.generation == 3


@pytest.mark.asyncio
async def test_empty_structural_diff_is_valid_not_rejected() -> None:
    # Re-trimming s1 to its existing bounds nets no field change, so the diff is
    # empty yet still valid — Apply would accept the batch and advance generation.
    h = _history()
    proposal = _proposal(
        [{"type": "trimSegment", "segment_id": "s1", "trim_start_seconds": 0.0, "trim_end_seconds": 4.0}]
    )
    diff = await compute_proposal_diff(h, proposal)
    assert diff.added == []
    assert diff.removed == []
    assert diff.modified == []
    assert diff.total_duration_before == diff.total_duration_after == 7.0


@pytest.mark.asyncio
async def test_preview_then_apply_then_undo_parity_with_manual_edit() -> None:
    # The preview -> apply path lands the AI batch as ONE undoable step, so undo
    # restores the exact pre-apply state — identical to undoing a manual batch.
    h = _history()
    original = h.present.model_dump(mode="json")
    proposal = _proposal(
        [
            {"type": "trimSegment", "segment_id": "s1", "trim_start_seconds": 1.0, "trim_end_seconds": 3.0},
            {"type": "deleteSegment", "segment_id": "s2", "policy": "ripple"},
        ]
    )
    diff = await compute_proposal_diff(h, proposal)
    assert [s.id for s in diff.removed] == ["s2"]

    applied = await apply_ai_proposal(h, proposal)
    assert [s.id for s in applied.segments] == ["s1"]
    assert h.generation == 4
    assert h.can_undo is True

    reverted = await h.undo()
    assert reverted.model_dump(mode="json") == original
    assert h.generation == 3


@pytest.mark.asyncio
async def test_cancel_is_a_noop_leaving_history_unchanged() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    proposal = _proposal([{"type": "deleteSegment", "segment_id": "s1", "policy": "ripple"}])
    await compute_proposal_diff(h, proposal)
    assert h.present.model_dump(mode="json") == before
    assert h.generation == 3
    assert h.can_undo is False
