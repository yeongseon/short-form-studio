"""SF-69: reusable transition presets shared by Inspector, Preview, and renderer.

A transition has two parts: the KIND (cut / fade / ken_burns / ken_burns_lite),
which is Timeline state applied via SetTransitionCommand, and the TIMING, which the
Timeline applier rejects and is therefore preview/render metadata. This module is
the single backend source of truth for the supported kinds and the timing rules,
mirrored from the frontend segmentTransition.ts so all three surfaces agree; a
drift test pins the supported set against the domain Literal and the compiler
frozenset.

Presets store a segment-agnostic duration_ratio, so a timed transition is always
in-bounds on short segments; resolving a preset for a segment yields the kind plus
an absolute resolved duration bounded by the shorter of the segment and its
previous neighbor. to_transition_command bridges only the kind onto the Timeline
(duration None, which the applier accepts), keeping the resolved duration as
preview/render metadata. Only the four simple supported kinds exist — no advanced
compositing. Malformed input raises a typed ValidationError.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from creator_domain.exceptions import ValidationError
from creator_domain.models import SetTransitionCommand

TransitionKind = Literal["cut", "fade", "ken_burns", "ken_burns_lite"]

SUPPORTED_TRANSITIONS: tuple[TransitionKind, ...] = (
    "cut",
    "fade",
    "ken_burns",
    "ken_burns_lite",
)
TIMED_TRANSITIONS: frozenset[str] = frozenset({"fade", "ken_burns", "ken_burns_lite"})
INSTANT_TRANSITIONS: frozenset[str] = frozenset({"cut"})


def _positive_finite(value: object, *, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{label} must be finite")
    if number <= 0:
        raise ValidationError(f"{label} must be positive")
    return number


def _bound(segment_duration: float, previous_duration: float | None) -> float:
    if previous_duration is None:
        return segment_duration
    return min(segment_duration, previous_duration)


@dataclass(frozen=True)
class TransitionPreset:
    id: str
    kind: TransitionKind
    duration_ratio: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValidationError("transition preset id must be a non-empty string")
        if self.kind not in SUPPORTED_TRANSITIONS:
            raise ValidationError(f"unsupported transition kind: {self.kind!r}")
        if self.kind in INSTANT_TRANSITIONS:
            if self.duration_ratio is not None:
                raise ValidationError("a cut transition preset must not have a duration_ratio")
        else:
            ratio = self.duration_ratio
            if not isinstance(ratio, (int, float)) or isinstance(ratio, bool):
                raise ValidationError("timed transition duration_ratio must be a number")
            if not math.isfinite(ratio) or ratio <= 0.0 or ratio > 1.0:
                raise ValidationError("timed transition duration_ratio must be within (0, 1]")


@dataclass(frozen=True)
class ResolvedTransition:
    kind: TransitionKind
    resolved_duration_seconds: float | None


TRANSITION_PRESETS: dict[str, TransitionPreset] = {
    "hard_cut": TransitionPreset(id="hard_cut", kind="cut"),
    "soft_fade": TransitionPreset(id="soft_fade", kind="fade", duration_ratio=0.3),
    "gentle_fade": TransitionPreset(id="gentle_fade", kind="fade", duration_ratio=0.5),
    "ken_burns_slow": TransitionPreset(
        id="ken_burns_slow", kind="ken_burns", duration_ratio=0.5
    ),
    "ken_burns_subtle": TransitionPreset(
        id="ken_burns_subtle", kind="ken_burns_lite", duration_ratio=0.3
    ),
}


def transition_preset_ids() -> tuple[str, ...]:
    """Return the shipped transition preset ids, sorted."""
    return tuple(sorted(TRANSITION_PRESETS))


def resolve_transition_preset(preset_id: str) -> TransitionPreset:
    """Resolve a named transition preset; unknown or non-string ids raise."""
    if not isinstance(preset_id, str) or preset_id not in TRANSITION_PRESETS:
        raise ValidationError(f"unknown transition preset: {preset_id!r}")
    return TRANSITION_PRESETS[preset_id]


def resolve_transition_timing(
    kind: str,
    duration_seconds: float | None,
    *,
    segment_duration: float,
    previous_duration: float | None,
) -> float | None:
    """Validate an ABSOLUTE transition duration against the neighbor bound.

    Mirrors the frontend segmentTransition.ts rules exactly: a cut is instantaneous
    and must have no duration; a timed transition requires a positive finite
    duration that does not exceed the shorter of the segment and its previous
    neighbor. An over-bound duration is rejected (not clamped), so absolute
    durations behave identically on every surface.
    """
    if kind not in SUPPORTED_TRANSITIONS:
        raise ValidationError(f"unsupported transition kind: {kind!r}")
    segment = _positive_finite(segment_duration, label="segment duration")
    previous = (
        _positive_finite(previous_duration, label="previous duration")
        if previous_duration is not None
        else None
    )
    if kind in INSTANT_TRANSITIONS:
        if duration_seconds is not None:
            raise ValidationError("a cut transition must not have a duration")
        return None
    duration = _positive_finite(duration_seconds, label="transition duration")
    bound = _bound(segment, previous)
    if duration > bound + 1e-9:
        raise ValidationError(
            f"transition duration {duration} exceeds the neighbor bound {bound}"
        )
    return duration


def resolve_transition_preset_for_segment(
    preset_id: str,
    *,
    segment_duration_seconds: float,
    previous_duration_seconds: float | None,
) -> ResolvedTransition:
    """Resolve a preset for a segment context into its kind and absolute duration.

    A cut resolves to no duration on any segment. A timed preset resolves to
    ``duration_ratio * bound`` where ``bound`` is the shorter of the segment and its
    previous neighbor, so the resolved duration is always in-bounds on short
    segments. Invalid segment context (non-positive/non-finite) raises.
    """
    preset = resolve_transition_preset(preset_id)
    segment = _positive_finite(segment_duration_seconds, label="segment duration")
    previous = (
        _positive_finite(previous_duration_seconds, label="previous duration")
        if previous_duration_seconds is not None
        else None
    )
    if preset.kind in INSTANT_TRANSITIONS:
        return ResolvedTransition(kind=preset.kind, resolved_duration_seconds=None)
    assert preset.duration_ratio is not None  # timed presets always carry a ratio
    resolved = preset.duration_ratio * _bound(segment, previous)
    return ResolvedTransition(kind=preset.kind, resolved_duration_seconds=resolved)


def to_transition_command(preset: TransitionPreset, *, segment_id: str) -> SetTransitionCommand:
    """Bridge a preset's KIND onto a target segment; duration stays render-time metadata.

    The Timeline applier rejects a transition duration, so only the kind is applied
    (duration_seconds=None). The resolved timing is exposed separately for preview
    and the renderer via resolve_transition_preset_for_segment.
    """
    return SetTransitionCommand(
        segment_id=segment_id, transition=preset.kind, duration_seconds=None
    )
