"""SF-48: shared validated EditorCommand boundary — typed command union.

The commands are the stable contract the editor UI and later AI use to express
timeline mutations. Each has a literal ``type`` so the union is a Pydantic
discriminated union that parses to the right concrete command and rejects
unknown types before any application.
"""

from __future__ import annotations

import pytest
from creator_domain.models import (
    DeleteSegmentCommand,
    EditorCommandModel,
    MoveSegmentCommand,
    ReplaceAssetCommand,
    ResizeSegmentCommand,
    SetAudioCommand,
    SetStyleCommand,
    SetTransitionCommand,
    SplitSegmentCommand,
    SwitchOutputCommand,
    TrimSegmentCommand,
)
from pydantic import ValidationError as PydanticValidationError


def _parse(payload: dict[str, object]) -> object:
    return EditorCommandModel.model_validate(payload).command


def test_parses_trim_segment() -> None:
    cmd = _parse(
        {
            "type": "trimSegment",
            "segment_id": "s1",
            "trim_start_seconds": 1.0,
            "trim_end_seconds": 5.0,
        }
    )
    assert isinstance(cmd, TrimSegmentCommand)
    assert cmd.segment_id == "s1"
    assert cmd.trim_start_seconds == 1.0
    assert cmd.trim_end_seconds == 5.0


def test_parses_split_segment() -> None:
    cmd = _parse({"type": "splitSegment", "segment_id": "s1", "at_seconds": 3.0})
    assert isinstance(cmd, SplitSegmentCommand)
    assert cmd.at_seconds == 3.0


def test_parses_delete_segment_with_policy() -> None:
    cmd = _parse({"type": "deleteSegment", "segment_id": "s1", "policy": "ripple"})
    assert isinstance(cmd, DeleteSegmentCommand)
    assert cmd.policy == "ripple"


def test_delete_segment_rejects_unknown_policy() -> None:
    with pytest.raises(PydanticValidationError):
        _parse({"type": "deleteSegment", "segment_id": "s1", "policy": "bogus"})


def test_parses_replace_asset() -> None:
    cmd = _parse({"type": "replaceAsset", "segment_id": "s1", "asset_id": 20})
    assert isinstance(cmd, ReplaceAssetCommand)
    assert cmd.asset_id == 20


def test_parses_move_segment() -> None:
    cmd = _parse({"type": "moveSegment", "segment_id": "s1", "target_index": 2})
    assert isinstance(cmd, MoveSegmentCommand)
    assert cmd.target_index == 2


def test_parses_resize_segment() -> None:
    cmd = _parse({"type": "resizeSegment", "segment_id": "s1", "duration_seconds": 6.0})
    assert isinstance(cmd, ResizeSegmentCommand)
    assert cmd.duration_seconds == 6.0


def test_parses_set_transition() -> None:
    cmd = _parse(
        {"type": "setTransition", "segment_id": "s1", "transition": "fade", "duration_seconds": 0.5}
    )
    assert isinstance(cmd, SetTransitionCommand)
    assert cmd.transition == "fade"


def test_set_transition_rejects_unsupported() -> None:
    with pytest.raises(PydanticValidationError):
        _parse({"type": "setTransition", "segment_id": "s1", "transition": "explode"})


def test_parses_switch_output() -> None:
    cmd = _parse({"type": "switchOutput", "preset": "short_square"})
    assert isinstance(cmd, SwitchOutputCommand)
    assert cmd.preset == "short_square"


def test_parses_set_style_and_audio() -> None:
    style = _parse({"type": "setStyle", "style": "cinematic"})
    audio = _parse({"type": "setAudio", "music_volume": 0.3})
    assert isinstance(style, SetStyleCommand)
    assert isinstance(audio, SetAudioCommand)


def test_rejects_unknown_command_type() -> None:
    with pytest.raises(PydanticValidationError):
        _parse({"type": "teleport", "segment_id": "s1"})


def test_requires_positive_asset_and_index_bounds() -> None:
    with pytest.raises(PydanticValidationError):
        _parse({"type": "replaceAsset", "segment_id": "s1", "asset_id": 0})
    with pytest.raises(PydanticValidationError):
        _parse({"type": "moveSegment", "segment_id": "s1", "target_index": -1})
