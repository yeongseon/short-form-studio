"""SF-69: reusable transition presets shared by Inspector, Preview, and renderer.

A transition has two parts: the KIND (cut / fade / ken_burns / ken_burns_lite),
which is Timeline state applied via SetTransitionCommand, and the TIMING, which the
Timeline applier rejects and is therefore preview/render metadata. This module is
the single backend source of truth for the supported kinds and the timing rules,
mirrored from the frontend segmentTransition.ts so all three surfaces agree; a
drift test pins the supported set against the domain Literal and the compiler
frozenset. Presets store a segment-agnostic duration_ratio so a timed transition is
always in-bounds on short segments; resolving a preset for a segment yields the
kind plus an absolute resolved duration, and to_command bridges the kind onto the
Timeline (duration None, which the applier accepts). Only the four simple supported
kinds exist — no advanced compositing.
"""

from __future__ import annotations

import typing

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import SetTransitionCommand, Timeline
from creator_domain.models.editor_commands import (
    _SUPPORTED_TRANSITIONS as _DOMAIN_SUPPORTED,
)
from creator_service.editor_command_applier import EditorAssetRef
from creator_service.editor_history import EditorHistory
from creator_service.timeline_compiler import (
    _SUPPORTED_TRANSITIONS as _COMPILER_SUPPORTED,
)
from creator_service.transition_preset import (
    INSTANT_TRANSITIONS,
    SUPPORTED_TRANSITIONS,
    TIMED_TRANSITIONS,
    TRANSITION_PRESETS,
    TransitionPreset,
    resolve_transition_preset,
    resolve_transition_preset_for_segment,
    resolve_transition_timing,
    to_transition_command,
    transition_preset_ids,
)


# ------------------------- registry validity -------------------------


def test_every_preset_is_valid() -> None:
    assert TRANSITION_PRESETS
    for preset_id, preset in TRANSITION_PRESETS.items():
        assert isinstance(preset, TransitionPreset)
        assert preset.id == preset_id
        assert preset.kind in SUPPORTED_TRANSITIONS
        if preset.kind in INSTANT_TRANSITIONS:
            assert preset.duration_ratio is None
        else:
            assert preset.duration_ratio is not None
            assert 0.0 < preset.duration_ratio <= 1.0


def test_preset_ids_are_a_sorted_immutable_tuple() -> None:
    ids = transition_preset_ids()
    assert isinstance(ids, tuple)
    assert list(ids) == sorted(TRANSITION_PRESETS)


def test_resolve_returns_the_registered_preset() -> None:
    any_id = transition_preset_ids()[0]
    assert resolve_transition_preset(any_id) == TRANSITION_PRESETS[any_id]


def test_resolve_rejects_unknown_preset_id() -> None:
    with pytest.raises(ValidationError, match="preset"):
        resolve_transition_preset("teleport")


@pytest.mark.parametrize("bad", [None, 123, True, ["hard_cut"]])
def test_resolve_rejects_non_string_preset_id(bad: object) -> None:
    with pytest.raises(ValidationError, match="preset"):
        resolve_transition_preset(bad)  # type: ignore[arg-type]


# ------------------------- shared-definition drift -------------------------


def test_supported_set_matches_the_domain_and_compiler_definitions() -> None:
    # The three surfaces must agree on the supported kinds; this pins the backend
    # module against both the domain Literal and the compiler allowlist so they
    # cannot silently drift apart.
    assert set(SUPPORTED_TRANSITIONS) == set(typing.get_args(_DOMAIN_SUPPORTED))
    assert set(SUPPORTED_TRANSITIONS) == set(_COMPILER_SUPPORTED)


def test_timed_and_instant_partition_the_supported_set() -> None:
    assert TIMED_TRANSITIONS | INSTANT_TRANSITIONS == set(SUPPORTED_TRANSITIONS)
    assert TIMED_TRANSITIONS & INSTANT_TRANSITIONS == set()
    assert "cut" in INSTANT_TRANSITIONS


# ------------------------- absolute timing validator parity -------------------------


def test_cut_requires_no_duration() -> None:
    resolve_transition_timing("cut", None, segment_duration=4.0, previous_duration=4.0)
    with pytest.raises(ValidationError, match="cut"):
        resolve_transition_timing("cut", 1.0, segment_duration=4.0, previous_duration=4.0)


@pytest.mark.parametrize("bad", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_timed_rejects_missing_or_non_positive_or_non_finite_duration(bad: object) -> None:
    with pytest.raises(ValidationError, match="duration"):
        resolve_transition_timing("fade", bad, segment_duration=4.0, previous_duration=4.0)  # type: ignore[arg-type]


def test_timed_rejects_a_duration_over_the_neighbor_bound() -> None:
    # bound = min(segment 4, previous 1) = 1; a 2s fade exceeds it.
    with pytest.raises(ValidationError, match="bound|exceed"):
        resolve_transition_timing("fade", 2.0, segment_duration=4.0, previous_duration=1.0)


def test_timed_accepts_a_duration_up_to_the_bound() -> None:
    resolved = resolve_transition_timing("fade", 1.0, segment_duration=4.0, previous_duration=1.0)
    assert resolved == pytest.approx(1.0)


def test_timing_validator_rejects_unsupported_kind() -> None:
    with pytest.raises(ValidationError, match="unsupported|transition"):
        resolve_transition_timing("wipe", 1.0, segment_duration=4.0, previous_duration=4.0)


# ------------------------- short-segment boundary resolution -------------------------


def test_resolving_a_timed_preset_is_bounded_by_the_shorter_neighbor() -> None:
    # gentle_fade ratio 0.5 against previous 1.0s -> 0.5s; against 0.2s -> 0.1s.
    a = resolve_transition_preset_for_segment(
        "gentle_fade", segment_duration_seconds=4.0, previous_duration_seconds=1.0
    )
    assert a.kind == "fade"
    assert a.resolved_duration_seconds == pytest.approx(0.5)

    b = resolve_transition_preset_for_segment(
        "gentle_fade", segment_duration_seconds=4.0, previous_duration_seconds=0.2
    )
    assert b.resolved_duration_seconds == pytest.approx(0.1)


def test_resolved_timed_duration_never_exceeds_the_bound() -> None:
    result = resolve_transition_preset_for_segment(
        "gentle_fade", segment_duration_seconds=0.3, previous_duration_seconds=0.3
    )
    assert result.resolved_duration_seconds is not None
    assert result.resolved_duration_seconds <= 0.3 + 1e-9


def test_cut_preset_resolves_to_no_duration_on_any_segment() -> None:
    result = resolve_transition_preset_for_segment(
        "hard_cut", segment_duration_seconds=0.1, previous_duration_seconds=0.1
    )
    assert result.kind == "cut"
    assert result.resolved_duration_seconds is None


def test_resolution_without_a_previous_neighbor_bounds_by_the_segment() -> None:
    result = resolve_transition_preset_for_segment(
        "gentle_fade", segment_duration_seconds=2.0, previous_duration_seconds=None
    )
    assert result.resolved_duration_seconds == pytest.approx(1.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_resolution_rejects_invalid_segment_context(bad: float) -> None:
    with pytest.raises(ValidationError, match="segment|duration"):
        resolve_transition_preset_for_segment(
            "gentle_fade", segment_duration_seconds=bad, previous_duration_seconds=1.0
        )


# ------------------------- kind -> Timeline command bridge -------------------------


def test_to_command_bridges_only_the_kind_with_no_duration() -> None:
    command = to_transition_command(resolve_transition_preset("gentle_fade"), segment_id="s1")
    assert isinstance(command, SetTransitionCommand)
    assert command.segment_id == "s1"
    assert command.transition == "fade"
    # duration is render-time metadata, never carried onto the Timeline command
    assert command.duration_seconds is None


def test_cut_preset_to_command() -> None:
    command = to_transition_command(resolve_transition_preset("hard_cut"), segment_id="s2")
    assert command.transition == "cut"
    assert command.duration_seconds is None


# ------------------------- preset construction validation -------------------------


def test_rejects_a_preset_with_an_unsupported_kind() -> None:
    with pytest.raises(ValidationError, match="transition|kind"):
        TransitionPreset(id="p", kind="wipe", duration_ratio=0.3)  # type: ignore[arg-type]


def test_rejects_a_cut_preset_with_a_duration_ratio() -> None:
    with pytest.raises(ValidationError, match="cut|ratio"):
        TransitionPreset(id="p", kind="cut", duration_ratio=0.3)


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5, float("nan"), float("inf"), None])
def test_rejects_a_timed_preset_with_an_out_of_band_ratio(bad: object) -> None:
    with pytest.raises(ValidationError, match="ratio"):
        TransitionPreset(id="p", kind="fade", duration_ratio=bad)  # type: ignore[arg-type]


def test_accepts_ratio_exactly_one() -> None:
    preset = TransitionPreset(id="p", kind="fade", duration_ratio=1.0)
    resolved = resolve_transition_preset_for_segment_value(preset, 2.0, 2.0)
    assert resolved == pytest.approx(2.0)


def resolve_transition_preset_for_segment_value(
    preset: TransitionPreset, seg: float, prev: float
) -> float | None:
    TRANSITION_PRESETS[preset.id] = preset
    try:
        return resolve_transition_preset_for_segment(
            preset.id, segment_duration_seconds=seg, previous_duration_seconds=prev
        ).resolved_duration_seconds
    finally:
        del TRANSITION_PRESETS[preset.id]


# ------------------------- reversible selection through the real Timeline -------------------------


class _FakeAssetLookup:
    def __init__(self, assets: dict[int, EditorAssetRef]) -> None:
        self._assets = assets

    async def get_asset_for_editor(
        self, asset_id: int, workspace_id: int
    ) -> EditorAssetRef | None:
        return self._assets.get(asset_id)


def _transition_history() -> EditorHistory:
    timeline = Timeline.model_validate(
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
                },
                {
                    "id": "s2",
                    "scene_id": "scene-1",
                    "asset_id": 11,
                    "timeline_start_seconds": 4.0,
                    "duration_seconds": 4.0,
                },
            ],
        }
    )
    lookup = _FakeAssetLookup(
        {
            10: EditorAssetRef(id=10, project_id=1, media_type="VIDEO", duration_seconds=30.0),
            11: EditorAssetRef(id=11, project_id=1, media_type="VIDEO", duration_seconds=30.0),
        }
    )
    return EditorHistory(timeline, workspace_id=1, asset_lookup=lookup)


def _transition_of(history: EditorHistory, segment_id: str) -> str | None:
    for segment in history.present.segments:
        if segment.id == segment_id:
            return segment.transition
    raise AssertionError(f"segment {segment_id} not found")


@pytest.mark.asyncio
async def test_preset_kind_selection_is_reversible_through_editor_history() -> None:
    # A preset's KIND is real Timeline state, so selecting presets through the
    # shared SetTransitionCommand + EditorHistory is reversible via the real undo
    # stack — no separate preset-selection history is introduced.
    history = _transition_history()

    await history.apply(to_transition_command(resolve_transition_preset("hard_cut"), segment_id="s2"))
    assert _transition_of(history, "s2") == "cut"

    await history.apply(to_transition_command(resolve_transition_preset("gentle_fade"), segment_id="s2"))
    assert _transition_of(history, "s2") == "fade"

    await history.undo()
    assert _transition_of(history, "s2") == "cut"

    await history.redo()
    assert _transition_of(history, "s2") == "fade"
