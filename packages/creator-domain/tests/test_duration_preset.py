"""SF-77: short-first duration presets (15/30/45/60/90 + Custom).

Locks that the shipped presets resolve to a ±10% DurationRange band and that
Custom durations have NO core ceiling — the ~3 minute guidance is a product-level
concern, never a domain clamp — so long custom shorts stay valid at the core.
"""

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import DurationRange
from creator_domain.models.duration_preset import (
    DURATION_PRESETS,
    duration_preset_ids,
    resolve_custom_duration,
    resolve_duration_preset,
)

_EXPECTED_IDS = ("15", "30", "45", "60", "90")


def test_preset_ids_are_the_shipped_shorts_ids_sorted_numerically() -> None:
    assert duration_preset_ids() == _EXPECTED_IDS


def test_each_preset_resolves_to_a_valid_plus_minus_10pct_band() -> None:
    for preset_id in _EXPECTED_IDS:
        nominal = float(preset_id)
        band = resolve_duration_preset(preset_id)
        assert isinstance(band, DurationRange)
        assert band.min_seconds == pytest.approx(0.9 * nominal)
        assert band.max_seconds == pytest.approx(1.1 * nominal)
        assert band.min_seconds <= band.max_seconds


def test_registry_matches_resolver() -> None:
    for preset_id in _EXPECTED_IDS:
        assert DURATION_PRESETS[preset_id] == resolve_duration_preset(preset_id)


def test_unknown_preset_raises_typed_validation_error() -> None:
    with pytest.raises(ValidationError):
        resolve_duration_preset("999")


def test_custom_duration_has_no_core_ceiling() -> None:
    for target in (15.0, 60.0, 90.0, 180.0, 181.0, 200.0):
        band = resolve_custom_duration(target)
        assert band.min_seconds == pytest.approx(0.9 * target)
        assert band.max_seconds == pytest.approx(1.1 * target)


def test_custom_duration_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        resolve_custom_duration(0.0)
    with pytest.raises(ValidationError):
        resolve_custom_duration(-5.0)


def test_resolvers_are_deterministic() -> None:
    assert resolve_duration_preset("30") == resolve_duration_preset("30")
    assert resolve_custom_duration(42.0) == resolve_custom_duration(42.0)
