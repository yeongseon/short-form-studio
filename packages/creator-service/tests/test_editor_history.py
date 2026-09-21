"""SF-49: Undo for accepted editor changes.

EditorHistory wraps apply_editor_command and records the pre-command Timeline
snapshot ONLY when a command (or a batch of commands) is accepted, so a failed
command never enters history. undo restores the exact prior snapshot. A batch of
commands (e.g. an accepted AI edit) is one undoable step.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import NoHistoryError, ValidationError
from creator_domain.models import (
    DeleteSegmentCommand,
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
async def test_starts_with_no_undo() -> None:
    h = _history()
    assert h.can_undo is False
    assert h.present.model_dump(mode="json") == _timeline().model_dump(mode="json")


@pytest.mark.asyncio
async def test_apply_records_history_and_enables_undo() -> None:
    h = _history()
    await h.apply(TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0))
    seg = next(s for s in h.present.segments if s.id == "s1")
    assert seg.trim_start_seconds == 1.0
    assert h.can_undo is True


@pytest.mark.asyncio
async def test_undo_restores_exact_prior_state() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    await h.apply(TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0))
    h.undo()
    assert h.present.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_undo_multiple_commands_in_reverse_order() -> None:
    h = _history()
    snapshot0 = h.present.model_dump(mode="json")
    await h.apply(TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0))
    snapshot1 = h.present.model_dump(mode="json")
    await h.apply(ResizeSegmentCommand(segment_id="s1", duration_seconds=1.5))
    h.undo()
    assert h.present.model_dump(mode="json") == snapshot1
    h.undo()
    assert h.present.model_dump(mode="json") == snapshot0
    assert h.can_undo is False


@pytest.mark.asyncio
async def test_failed_command_does_not_enter_history() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    with pytest.raises(ValidationError):
        await h.apply(TrimSegmentCommand(segment_id="nope", trim_start_seconds=0.0, trim_end_seconds=1.0))
    assert h.can_undo is False
    assert h.present.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_undo_at_boundary_raises() -> None:
    h = _history()
    with pytest.raises(NoHistoryError):
        h.undo()


@pytest.mark.asyncio
async def test_apply_batch_is_one_undoable_step() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    await h.apply_batch(
        [
            TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0),
            DeleteSegmentCommand(segment_id="s2", policy="ripple"),
        ]
    )
    assert len(h.present.segments) == 1
    h.undo()
    assert h.present.model_dump(mode="json") == before
    assert h.can_undo is False


@pytest.mark.asyncio
async def test_failed_batch_is_atomic_and_not_recorded() -> None:
    h = _history()
    before = h.present.model_dump(mode="json")
    with pytest.raises(ValidationError):
        await h.apply_batch(
            [
                TrimSegmentCommand(segment_id="s1", trim_start_seconds=1.0, trim_end_seconds=3.0),
                TrimSegmentCommand(segment_id="nope", trim_start_seconds=0.0, trim_end_seconds=1.0),
            ]
        )
    assert h.can_undo is False
    assert h.present.model_dump(mode="json") == before
