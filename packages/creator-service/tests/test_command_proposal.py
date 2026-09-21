"""SF-55: parse an LLM response into a structured EditorCommand proposal.

parse_command_proposal takes a raw LLM string, extracts the JSON batch, and
validates each command through the shared EditorCommandModel discriminated union
(SF-48). Malformed JSON or unknown/malformed commands are rejected as a whole —
nothing is applied. The proposal carries the base_revision it was generated
against so the applier can reject a stale batch.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    DeleteSegmentCommand,
    TrimSegmentCommand,
)
from creator_service.command_proposal import parse_command_proposal


def _payload(commands: str) -> str:
    return '{"base_revision": 7, "commands": ' + commands + "}"


def test_parses_a_typed_command_batch() -> None:
    raw = _payload(
        '[{"type": "trimSegment", "segment_id": "s1", "trim_start_seconds": 1.0, '
        '"trim_end_seconds": 3.0}, {"type": "deleteSegment", "segment_id": "s2", '
        '"policy": "ripple"}]'
    )
    proposal = parse_command_proposal(raw, base_revision=7)
    assert proposal.base_revision == 7
    assert len(proposal.commands) == 2
    assert isinstance(proposal.commands[0], TrimSegmentCommand)
    assert isinstance(proposal.commands[1], DeleteSegmentCommand)
    assert proposal.commands[0].segment_id == "s1"


def test_preserves_stable_target_ids() -> None:
    raw = _payload('[{"type": "resizeSegment", "segment_id": "scene-9-seg", "duration_seconds": 2.0}]')
    proposal = parse_command_proposal(raw, base_revision=7)
    assert proposal.commands[0].segment_id == "scene-9-seg"


def test_extracts_json_from_surrounding_prose() -> None:
    raw = (
        "Sure! Here is the edit:\n```json\n"
        + _payload('[{"type": "setTransition", "segment_id": "s1", "transition": "fade"}]')
        + "\n```\nHope that helps."
    )
    proposal = parse_command_proposal(raw, base_revision=7)
    assert len(proposal.commands) == 1


def test_rejects_invalid_json() -> None:
    with pytest.raises(ValidationError):
        parse_command_proposal("not json at all", base_revision=7)


def test_rejects_json_that_is_not_a_command_object() -> None:
    with pytest.raises(ValidationError):
        parse_command_proposal("[1, 2, 3]", base_revision=7)


def test_rejects_unknown_command_type_without_applying() -> None:
    raw = _payload('[{"type": "teleportSegment", "segment_id": "s1"}]')
    with pytest.raises(ValidationError):
        parse_command_proposal(raw, base_revision=7)


def test_rejects_malformed_command_shape() -> None:
    # trimSegment missing required trim_end_seconds
    raw = _payload('[{"type": "trimSegment", "segment_id": "s1", "trim_start_seconds": 1.0}]')
    with pytest.raises(ValidationError):
        parse_command_proposal(raw, base_revision=7)


def test_rejects_a_batch_when_any_command_is_invalid() -> None:
    raw = _payload(
        '[{"type": "deleteSegment", "segment_id": "s1"}, '
        '{"type": "teleportSegment", "segment_id": "s2"}]'
    )
    with pytest.raises(ValidationError):
        parse_command_proposal(raw, base_revision=7)


def test_rejects_a_stale_base_revision() -> None:
    raw = _payload('[{"type": "deleteSegment", "segment_id": "s1"}]')
    with pytest.raises(ValidationError):
        parse_command_proposal(raw, base_revision=8)


def test_rejects_an_empty_command_batch() -> None:
    raw = _payload("[]")
    with pytest.raises(ValidationError):
        parse_command_proposal(raw, base_revision=7)


def test_rejects_a_batch_exceeding_the_command_bound() -> None:
    commands = ",".join(
        '{"type": "deleteSegment", "segment_id": "s' + str(i) + '"}' for i in range(60)
    )
    raw = _payload("[" + commands + "]")
    with pytest.raises(ValidationError):
        parse_command_proposal(raw, base_revision=7, max_commands=50)
