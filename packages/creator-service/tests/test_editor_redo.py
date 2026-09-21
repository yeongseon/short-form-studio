"""SF-50: Redo for undone editor changes.

Redo replays undone accepted changes deterministically. undo moves the present
onto a redo (future) stack; redo pops it back. Any new accepted edit clears the
redo branch, so redo never replays a change that a later edit diverged from.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import NoHistoryError, ValidationError
from creator_domain.models import (
    ResizeSegmentCommand,
    Timeline,
    TrimSegmentCommand,
)
from creator_service.editor_command_applier import EditorAssetRef
from creator_service.editor_history import EditorHistory


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


def _history() -> EditorHistory:
    lookup = _FakeAssetLookup({10: _ref(10), 11: _ref(11)})
    return EditorHistory(_timeline(), workspace_id=1, asset_lookup=lookup)


@pytest.mark.asyncio
async def test_starts_with_no_redo() -> None:
    h = _history()
    assert h.can_redo is False


@pytest.mark.asyncio
async def test_undo_enables_redo() -> None:
    h = _history()
    await h.apply(TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0))
    assert h.can_redo is False
    await h.undo()
    assert h.can_redo is True


@pytest.mark.asyncio
async def test_redo_replays_the_undone_change_exactly() -> None:
    h = _history()
    await h.apply(TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0))
    after_apply = h.present.model_dump(mode="json")
    await h.undo()
    await h.redo()
    assert h.present.model_dump(mode="json") == after_apply
    assert h.can_redo is False


@pytest.mark.asyncio
async def test_repeated_undo_redo_is_deterministic() -> None:
    h = _history()
    await h.apply(TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0))
    snap = h.present.model_dump(mode="json")
    for _ in range(3):
        await h.undo()
        await h.redo()
    assert h.present.model_dump(mode="json") == snap


@pytest.mark.asyncio
async def test_redo_stack_across_multiple_commands() -> None:
    h = _history()
    s0 = h.present.model_dump(mode="json")
    await h.apply(TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0))
    s1 = h.present.model_dump(mode="json")
    await h.apply(ResizeSegmentCommand(segment_id="s1", duration_seconds=1.5))
    s2 = h.present.model_dump(mode="json")
    await h.undo()
    await h.undo()
    assert h.present.model_dump(mode="json") == s0
    await h.redo()
    assert h.present.model_dump(mode="json") == s1
    await h.redo()
    assert h.present.model_dump(mode="json") == s2


@pytest.mark.asyncio
async def test_new_apply_clears_redo_branch() -> None:
    h = _history()
    await h.apply(TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0))
    await h.undo()
    assert h.can_redo is True
    await h.apply(ResizeSegmentCommand(segment_id="s1", duration_seconds=1.5))
    assert h.can_redo is False
    with pytest.raises(NoHistoryError):
        await h.redo()


@pytest.mark.asyncio
async def test_batch_undo_redo_is_one_step() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    await h.apply_batch(
        [
            TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0),
            ResizeSegmentCommand(segment_id="s1", duration_seconds=1.5),
        ]
    )
    after = h.present.model_dump(mode="json")
    await h.undo()
    assert h.present.model_dump(mode="json") == before
    await h.redo()
    assert h.present.model_dump(mode="json") == after


@pytest.mark.asyncio
async def test_redo_at_boundary_raises() -> None:
    h = _history()
    with pytest.raises(NoHistoryError):
        await h.redo()


@pytest.mark.asyncio
async def test_failed_command_does_not_clear_redo_branch() -> None:
    h = _history()
    await h.apply(TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0))
    await h.undo()
    with pytest.raises(ValidationError):
        await h.apply(TrimSegmentCommand(segment_id="nope", trim_start_seconds=0.0, trim_end_seconds=1.0))
    # a rejected command is not an accepted edit, so the redo branch survives
    assert h.can_redo is True


@pytest.mark.asyncio
async def test_redo_snapshot_is_defensively_copied() -> None:
    h = _history()
    await h.apply(TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0))
    after = h.present.model_dump(mode="json")
    await h.undo()
    held = h.present
    # mutate the object now on the redo stack's counterpart
    held.segments[0].trim_start_seconds = 42.0
    await h.redo()
    assert h.present.model_dump(mode="json") == after
