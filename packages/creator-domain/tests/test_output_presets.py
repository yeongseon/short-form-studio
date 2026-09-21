from __future__ import annotations

import pytest
from creator_domain.models import AspectRatio, OutputSpec


def test_short_vertical_preset() -> None:
    spec = OutputSpec.short_vertical()
    assert (spec.width, spec.height) == (1080, 1920)
    assert spec.fps == 30
    assert spec.aspect_ratio is AspectRatio.VERTICAL


def test_short_square_preset() -> None:
    spec = OutputSpec.short_square()
    assert (spec.width, spec.height) == (1080, 1080)
    assert spec.fps == 30
    assert spec.aspect_ratio is AspectRatio.SQUARE


def test_short_landscape_preset() -> None:
    spec = OutputSpec.short_landscape()
    assert (spec.width, spec.height) == (1920, 1080)
    assert spec.fps == 30
    assert spec.aspect_ratio is AspectRatio.LANDSCAPE


def test_preset_by_name_resolves_all_three() -> None:
    assert OutputSpec.preset("short_vertical") == OutputSpec.short_vertical()
    assert OutputSpec.preset("short_square") == OutputSpec.short_square()
    assert OutputSpec.preset("short_landscape") == OutputSpec.short_landscape()


def test_preset_by_name_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        OutputSpec.preset("short_cinema")


def test_presets_are_platform_agnostic_geometry_only() -> None:
    # Core presets carry geometry, not platform names (Shorts/Reels/TikTok live
    # in the product layer, not the core value object).
    for spec in (
        OutputSpec.short_vertical(),
        OutputSpec.short_square(),
        OutputSpec.short_landscape(),
    ):
        assert set(spec.model_dump()) == {"width", "height", "fps"}
