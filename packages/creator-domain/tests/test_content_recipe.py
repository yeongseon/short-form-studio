from __future__ import annotations

import pytest
from creator_domain.models import ContentRecipe
from pydantic import ValidationError


def _recipe_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "shorts_knowledge",
        "target_duration": {"min_seconds": 30, "max_seconds": 60},
        "structure": ["hook", "explanation", "key_point", "conclusion"],
        "visual_strategy": {
            "pacing": "fast",
            "segment_duration": {"min_seconds": 2.0, "max_seconds": 6.0},
        },
        "audio": {"narration": True, "bgm": True},
        "subtitles": {"enabled": True, "emphasis": True},
    }
    payload.update(overrides)
    return payload


def test_content_recipe_minimal_valid() -> None:
    recipe = ContentRecipe.model_validate(_recipe_payload())

    assert recipe.id == "shorts_knowledge"
    assert recipe.target_duration.min_seconds == 30
    assert recipe.target_duration.max_seconds == 60
    assert recipe.structure == ["hook", "explanation", "key_point", "conclusion"]
    assert recipe.visual_strategy.pacing == "fast"
    assert recipe.visual_strategy.segment_duration.min_seconds == 2.0
    assert recipe.audio.narration is True
    assert recipe.audio.bgm is True
    assert recipe.subtitles.enabled is True
    assert recipe.subtitles.emphasis is True


def test_content_format_defaults_to_none_and_is_optional() -> None:
    recipe = ContentRecipe.model_validate(_recipe_payload())
    assert recipe.content_format is None


def test_content_format_accepts_short() -> None:
    recipe = ContentRecipe.model_validate(_recipe_payload(content_format="short"))
    assert recipe.content_format == "short"


def test_content_format_is_extensible_not_short_only() -> None:
    # The schema must not hard-restrict content_format to "short" (future
    # long-form must be addable without a schema change).
    recipe = ContentRecipe.model_validate(_recipe_payload(content_format="long"))
    assert recipe.content_format == "long"


def test_target_duration_rejects_min_greater_than_max() -> None:
    with pytest.raises(ValidationError):
        ContentRecipe.model_validate(
            _recipe_payload(target_duration={"min_seconds": 90, "max_seconds": 30})
        )


def test_target_duration_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        ContentRecipe.model_validate(
            _recipe_payload(target_duration={"min_seconds": 0, "max_seconds": 30})
        )


def test_segment_duration_rejects_min_greater_than_max() -> None:
    with pytest.raises(ValidationError):
        ContentRecipe.model_validate(
            _recipe_payload(
                visual_strategy={
                    "pacing": "fast",
                    "segment_duration": {"min_seconds": 6.0, "max_seconds": 2.0},
                }
            )
        )


def test_structure_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        ContentRecipe.model_validate(_recipe_payload(structure=[]))


def test_recipe_rejects_unknown_top_level_field() -> None:
    with pytest.raises(ValidationError):
        ContentRecipe.model_validate(_recipe_payload(unexpected="x"))


def test_recipe_round_trips_via_json() -> None:
    recipe = ContentRecipe.model_validate(_recipe_payload(content_format="short"))
    restored = ContentRecipe.model_validate_json(recipe.to_json())
    assert restored == recipe


def test_recipe_no_short_only_duration_ceiling() -> None:
    # A generic recipe schema must allow long target durations; the 3-minute UI
    # cap is a product concern, not a core schema invariant.
    recipe = ContentRecipe.model_validate(
        _recipe_payload(target_duration={"min_seconds": 600, "max_seconds": 1200})
    )
    assert recipe.target_duration.max_seconds == 1200
