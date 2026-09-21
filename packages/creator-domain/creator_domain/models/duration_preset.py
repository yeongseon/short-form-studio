"""SF-77: short-first duration presets as DurationRange value objects.

The shipped presets (15/30/45/60/90 seconds) each resolve to a ±10% tolerance
band so a draft's per-segment feasibility can intersect the target. Custom
durations validate only that the target is positive — the ~3 minute figure is
product-level onboarding guidance, never a core ceiling — so long shorts stay
valid at the domain layer.
"""

from __future__ import annotations

from creator_domain.exceptions import ValidationError
from creator_domain.models.content_recipe import DurationRange

_TOLERANCE = 0.1

_NOMINAL_SECONDS: tuple[int, ...] = (15, 30, 45, 60, 90)


def _band(nominal: float) -> DurationRange:
    try:
        return DurationRange(
            min_seconds=(1.0 - _TOLERANCE) * nominal,
            max_seconds=(1.0 + _TOLERANCE) * nominal,
        )
    except ValueError as error:
        raise ValidationError(str(error)) from error


DURATION_PRESETS: dict[str, DurationRange] = {
    str(nominal): _band(float(nominal)) for nominal in _NOMINAL_SECONDS
}


def duration_preset_ids() -> tuple[str, ...]:
    return tuple(sorted(DURATION_PRESETS, key=lambda preset_id: int(preset_id)))


def resolve_duration_preset(preset_id: str) -> DurationRange:
    band = DURATION_PRESETS.get(preset_id)
    if band is None:
        raise ValidationError(f"unknown duration preset: {preset_id!r}")
    return band


def resolve_custom_duration(target_seconds: float) -> DurationRange:
    if target_seconds <= 0:
        raise ValidationError("custom duration target_seconds must be > 0")
    return _band(target_seconds)
