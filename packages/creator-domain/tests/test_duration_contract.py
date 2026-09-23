import operator

import pytest
from pydantic import ValidationError as PydanticValidationError

from creator_domain.exceptions import ValidationError
from creator_domain.models.content_recipe import DurationRange
from creator_domain.models.duration_preset import (
    DURATION_PRESETS,
    resolve_custom_duration,
    resolve_duration_preset,
)


@pytest.mark.parametrize("seconds", [float("inf"), float("-inf"), float("nan")])
def test_custom_duration_rejects_nonfinite_input(seconds: float) -> None:
    # Given a nonfinite duration; when resolved; then domain validation fails.
    with pytest.raises(ValidationError):
        resolve_custom_duration(seconds)


@pytest.mark.parametrize("bounds", [(1, float("inf")), (float("inf"), float("inf")),
                                    (float("nan"), 2), (1, float("nan"))])
def test_duration_range_rejects_nonfinite_bounds(bounds: tuple[float, float]) -> None:
    # Given nonfinite bounds; when parsed directly; then validation fails.
    with pytest.raises(PydanticValidationError):
        DurationRange(min_seconds=bounds[0], max_seconds=bounds[1])


def test_preset_value_cannot_be_mutated() -> None:
    # Given a shared preset; when its bounds are changed; then mutation is rejected.
    preset = resolve_duration_preset("30")
    try:
        with pytest.raises(PydanticValidationError):
            preset.min_seconds = 1
    finally:
        # Restore the pre-fix mutable object so the RED run stays isolated.
        if preset.min_seconds == 1:
            preset.min_seconds = 27


def test_preset_registry_cannot_be_mutated() -> None:
    # Given shared presets; when a caller replaces an entry; then mutation fails.
    original = DURATION_PRESETS["30"]
    try:
        with pytest.raises(TypeError):
            operator.setitem(DURATION_PRESETS, "30", DurationRange(min_seconds=1, max_seconds=2))
    finally:
        if DURATION_PRESETS["30"] is not original:
            operator.setitem(DURATION_PRESETS, "30", original)


def test_finite_long_duration_remains_supported() -> None:
    # Given a duration beyond onboarding guidance; when resolved; then no ceiling applies.
    duration = resolve_custom_duration(600)
    assert (duration.min_seconds, duration.max_seconds) == pytest.approx((540, 660))
