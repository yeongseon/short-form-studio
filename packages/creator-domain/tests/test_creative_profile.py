from __future__ import annotations

import pytest
from creator_domain.models import CreativeProfile
from pydantic import ValidationError


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "cinematic",
        "transition": "fade",
        "color_grade": "warm",
        "motion": "ken_burns",
        "subtitle_emphasis": True,
    }
    payload.update(overrides)
    return payload


def test_creative_profile_minimal_valid() -> None:
    profile = CreativeProfile.model_validate(_payload())
    assert profile.id == "cinematic"
    assert profile.transition == "fade"
    assert profile.color_grade == "warm"
    assert profile.motion == "ken_burns"
    assert profile.subtitle_emphasis is True


def test_creative_profile_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CreativeProfile.model_validate(_payload(unexpected="x"))


def test_creative_profile_rejects_empty_id() -> None:
    with pytest.raises(ValidationError):
        CreativeProfile.model_validate(_payload(id=""))


def test_creative_profile_round_trips_via_json() -> None:
    profile = CreativeProfile.model_validate(_payload())
    restored = CreativeProfile.model_validate_json(profile.to_json())
    assert restored == profile


# --- the six shipped presets ------------------------------------------------


def test_all_six_presets_resolve() -> None:
    ids = {
        "default",
        "cinematic",
        "minimal",
        "energetic",
        "story",
        "product",
    }
    assert set(CreativeProfile.preset_ids()) == ids
    for pid in ids:
        profile = CreativeProfile.preset(pid)
        assert isinstance(profile, CreativeProfile)
        assert profile.id == pid


def test_preset_lookup_rejects_unknown_without_hidden_fallback() -> None:
    # No hidden niche fallback: an unknown creative profile id raises rather
    # than silently returning ssul_v2/default.
    with pytest.raises(ValueError):
        CreativeProfile.preset("ssul_v2")
    with pytest.raises(ValueError):
        CreativeProfile.preset("totally_unknown")


def test_named_preset_factories() -> None:
    assert CreativeProfile.default().id == "default"
    assert CreativeProfile.cinematic().id == "cinematic"
    assert CreativeProfile.minimal().id == "minimal"
    assert CreativeProfile.energetic().id == "energetic"
    assert CreativeProfile.story().id == "story"
    assert CreativeProfile.product().id == "product"


def test_presets_are_distinct_look_and_feel() -> None:
    # Look/feel must actually differ across presets (not all identical defaults).
    transitions = {CreativeProfile.preset(pid).transition for pid in CreativeProfile.preset_ids()}
    assert len(transitions) >= 2


def test_creative_profile_is_separate_from_recipe_and_output() -> None:
    # CreativeProfile carries look/feel only — no structure or geometry fields.
    fields = set(CreativeProfile.model_fields)
    assert "structure" not in fields
    assert "target_duration" not in fields
    assert "width" not in fields
    assert "height" not in fields
