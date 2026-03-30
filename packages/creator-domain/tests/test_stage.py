import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import (  # noqa: E402
    GENERATING_STAGES,
    REVIEW_STAGES,
    TRANSITIONS,
    RunStage,
    advance,
    can_transition,
    next_stages,
)


def test_all_valid_transitions_are_allowed() -> None:
    for current, targets in TRANSITIONS.items():
        for target in targets:
            assert can_transition(current, target)


def test_invalid_transition_returns_false() -> None:
    assert not can_transition(RunStage.IDEA_READY, RunStage.PUBLISHED)
    assert not can_transition(RunStage.PUBLISHED, RunStage.FAILED)
    assert not can_transition(RunStage.FAILED, RunStage.IDEA_READY)


def test_advance_raises_for_stages_without_single_non_failed_path() -> None:
    with pytest.raises(ValueError):
        advance(RunStage.SCRIPT_REVIEW)

    with pytest.raises(ValueError):
        advance(RunStage.FINAL_REVIEW)

    with pytest.raises(ValueError):
        advance(RunStage.PUBLISHED)

    with pytest.raises(ValueError):
        advance(RunStage.FAILED)


def test_happy_path_sequence_idea_ready_to_published() -> None:
    happy_path = [
        RunStage.IDEA_READY,
        RunStage.SCRIPT_GENERATING,
        RunStage.SCRIPT_REVIEW,
        RunStage.VISUAL_PLAN_GENERATING,
        RunStage.VISUAL_PLAN_REVIEW,
        RunStage.VISUAL_ASSET_GENERATING,
        RunStage.VISUAL_ASSET_REVIEW,
        RunStage.AUDIO_GENERATING,
        RunStage.SUBTITLE_GENERATING,
        RunStage.RENDER_GENERATING,
        RunStage.FINAL_REVIEW,
        RunStage.PUBLISHED,
    ]

    for current, nxt in zip(happy_path, happy_path[1:], strict=False):
        assert can_transition(current, nxt)


def test_failed_is_reachable_from_all_generating_stages() -> None:
    for stage in GENERATING_STAGES:
        assert RunStage.FAILED in next_stages(stage)


def test_next_stages_match_transition_map() -> None:
    for stage in RunStage:
        assert next_stages(stage) == list(TRANSITIONS[stage])


def test_stage_group_sets() -> None:
    assert {
        RunStage.SCRIPT_REVIEW,
        RunStage.VISUAL_PLAN_REVIEW,
        RunStage.VISUAL_ASSET_REVIEW,
        RunStage.FINAL_REVIEW,
    } == REVIEW_STAGES
    assert {
        RunStage.SCRIPT_GENERATING,
        RunStage.VISUAL_PLAN_GENERATING,
        RunStage.VISUAL_ASSET_GENERATING,
        RunStage.AUDIO_GENERATING,
        RunStage.SUBTITLE_GENERATING,
        RunStage.RENDER_GENERATING,
    } == GENERATING_STAGES


def test_run_stage_str_returns_value() -> None:
    """Regression: str(RunStage.X) must return the raw value, not 'RunStage.X'."""
    for stage in RunStage:
        assert str(stage) == stage.value
