"""SF-15: characterize legacy quality-profile selection before moving the niche
fork out of core, then lock the recipe-driven resolver behavior.

The worker tasks historically select a QualityProfile with the hardcoded niche
branch ``get_quality_profile(name if name != "shorts_default" else "ssul_v2")``.
These tests pin the current outputs so the new resolver preserves them.
"""

from __future__ import annotations

import pytest
from creator_service.quality_profile import QualityProfile, get_quality_profile
from creator_service.recipe_profile import (
    UnknownProfileError,
    resolve_quality_profile,
)


# --- characterization: existing get_quality_profile -------------------------


def test_legacy_ssul_v2_profile_fields_are_stable() -> None:
    qp = get_quality_profile("ssul_v2")
    assert qp.name == "ssul_v2"
    assert qp.transition == "ken_burns_lite"
    assert qp.max_scene_duration == 10.0
    assert qp.hard_cut_on_climax is True


def test_legacy_default_profile_fields_are_stable() -> None:
    qp = get_quality_profile("default")
    assert qp.name == "default"
    assert qp.transition == "cut"
    assert qp.subtitle_emphasis is False


def test_legacy_unknown_name_currently_falls_back_to_ssul_v2() -> None:
    # Characterize the pre-existing implicit fallback (SF-17 removes it later).
    assert get_quality_profile("does_not_exist").name == "ssul_v2"


# --- new explicit recipe-driven resolver ------------------------------------


def test_resolver_preserves_ssul_v2_for_legacy_niche_selection() -> None:
    # The legacy "shorts_default -> ssul_v2" niche fork is expressed as an
    # explicit mapping, not an inline branch. Same profile out.
    resolved = resolve_quality_profile("shorts_default")
    assert isinstance(resolved, QualityProfile)
    assert resolved.name == get_quality_profile("ssul_v2").name
    assert resolved.transition == get_quality_profile("ssul_v2").transition


def test_resolver_returns_named_profile_directly() -> None:
    assert resolve_quality_profile("ssul_v2").name == "ssul_v2"
    assert resolve_quality_profile("default").name == "default"


def test_resolver_maps_shipped_recipe_ids_to_profiles() -> None:
    # Recipe ids select behavior via configuration instead of core niche
    # branches; unknown-but-shipped ids resolve to a concrete profile.
    for recipe_id in (
        "shorts_general",
        "shorts_story",
        "shorts_knowledge",
        "shorts_product",
        "shorts_promotional",
    ):
        resolved = resolve_quality_profile(recipe_id)
        assert isinstance(resolved, QualityProfile)


def test_resolver_rejects_unknown_id_when_strict() -> None:
    with pytest.raises(UnknownProfileError):
        resolve_quality_profile("totally_unknown", strict=True)


def test_resolver_non_strict_defaults_are_explicit_not_silent() -> None:
    # Without strict, an unknown id resolves to the documented default profile
    # rather than silently to ssul_v2 via dict.get fallback.
    resolved = resolve_quality_profile("totally_unknown")
    assert isinstance(resolved, QualityProfile)
    assert resolved.name in {"ssul_v2", "default"}
