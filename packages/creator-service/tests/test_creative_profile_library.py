"""SF-70: reusable CreativeProfile library for templates and drafts.

The six creative profiles already live on the domain CreativeProfile model; this
service-layer library is the thin reusable resolver surface that templates and
drafts share, DELEGATING to the domain presets (no copied factories) and exposing
them through the same typed, immutable contract as the other preset libraries
(sorted-tuple ids, ValidationError on bad ids). Style stays separate from recipe,
output, and encoding — the profile carries only look-and-feel fields — and there is
no implicit fallback: an unknown or legacy id raises loudly so a saved project
reproduces its exact style or fails visibly.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import CreativeProfile
from creator_service.creative_profile_library import (
    creative_profile_ids,
    creative_profile_library,
    resolve_creative_profile,
)

_AC_IDS = ("default", "cinematic", "minimal", "energetic", "story", "product")

# The exact field values are the saved-project reproducibility contract: an
# accidental change to any preset must fail this test.
_EXPECTED = {
    "default": ("cut", "neutral", "none", False),
    "cinematic": ("fade", "warm", "ken_burns", True),
    "minimal": ("cut", "neutral", "none", False),
    "energetic": ("whip", "vivid", "fast_zoom", True),
    "story": ("ken_burns_lite", "moody", "ken_burns", True),
    "product": ("fade", "clean", "slow_pan", True),
}


# ------------------------- exposed ids -------------------------


def test_exposes_the_six_acceptance_profiles() -> None:
    assert set(creative_profile_ids()) == set(_AC_IDS)


def test_ids_are_a_sorted_immutable_tuple() -> None:
    ids = creative_profile_ids()
    assert isinstance(ids, tuple)
    assert list(ids) == sorted(_AC_IDS)


# ------------------------- resolution + reproducibility -------------------------


@pytest.mark.parametrize("profile_id", _AC_IDS)
def test_resolves_each_profile_to_its_exact_documented_style(profile_id: str) -> None:
    profile = resolve_creative_profile(profile_id)
    assert isinstance(profile, CreativeProfile)
    assert profile.id == profile_id
    transition, color_grade, motion, emphasis = _EXPECTED[profile_id]
    assert profile.transition == transition
    assert profile.color_grade == color_grade
    assert profile.motion == motion
    assert profile.subtitle_emphasis is emphasis


@pytest.mark.parametrize("profile_id", _AC_IDS)
def test_resolving_the_same_id_is_deterministic(profile_id: str) -> None:
    assert resolve_creative_profile(profile_id) == resolve_creative_profile(profile_id)


# ------------------------- error behavior + no fallback -------------------------


def test_unknown_id_raises_and_preserves_the_domain_cause() -> None:
    with pytest.raises(ValidationError, match="creative profile") as exc:
        resolve_creative_profile("unknown")
    assert isinstance(exc.value.__cause__, ValueError)


@pytest.mark.parametrize("bad", [None, 123, True, ["default"], ""])
def test_non_string_or_blank_id_raises(bad: object) -> None:
    with pytest.raises(ValidationError, match="creative profile"):
        resolve_creative_profile(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("legacy", ["shorts_default", "ssul_v2", "", "unknown"])
def test_no_implicit_fallback_to_a_default_or_ssul_profile(legacy: str) -> None:
    # A legacy/unknown id must RAISE, never silently resolve to default/ssul — so a
    # saved project with a bad id fails loudly instead of rendering the wrong style.
    with pytest.raises(ValidationError):
        resolve_creative_profile(legacy)


# ------------------------- style separation -------------------------


def test_creative_profile_carries_only_look_and_feel_fields() -> None:
    # Style stays separate from recipe / output / encoding: the model must expose
    # exactly the look-and-feel fields and none of the other domains' fields.
    assert set(CreativeProfile.model_fields) == {
        "id",
        "transition",
        "color_grade",
        "motion",
        "subtitle_emphasis",
    }
    for foreign in (
        "recipe",
        "recipe_id",
        "output",
        "output_spec",
        "encoding",
        "encoding_profile",
        "target_duration",
        "duration",
    ):
        assert foreign not in CreativeProfile.model_fields


# ------------------------- enumeration -------------------------


def test_library_enumerates_all_profiles_matching_resolve() -> None:
    library = creative_profile_library()
    assert set(library) == set(_AC_IDS)
    for profile_id, profile in library.items():
        assert profile == resolve_creative_profile(profile_id)


def test_library_returns_fresh_profiles_not_a_shared_mutable_singleton() -> None:
    first = creative_profile_library()
    second = creative_profile_library()
    assert first == second
    assert first["story"] is not second["story"]


# ------------------------- template/draft reuse -------------------------


def test_a_short_template_resolves_the_same_profile_as_the_library() -> None:
    from creator_service.recipe_registry import get_recipe_registry
    from creator_service.short_template import SHORT_TEMPLATES, resolve_short_template

    resolved = resolve_short_template(
        SHORT_TEMPLATES["story"], recipe_registry=get_recipe_registry()
    )
    assert resolved.creative_profile == resolve_creative_profile("story")
