from __future__ import annotations

from pathlib import Path

import pytest
from creator_domain.models import ContentRecipe
from creator_service.recipe_registry import (
    RecipeNotFoundError,
    RecipeRegistry,
    load_shorts_recipes,
)

_VALID_YAML = """
id: shorts_knowledge
target_duration:
  min_seconds: 30
  max_seconds: 60
structure:
  - hook
  - explanation
  - key_point
  - conclusion
visual_strategy:
  pacing: fast
  segment_duration:
    min_seconds: 2.0
    max_seconds: 6.0
audio:
  narration: true
  bgm: true
subtitles:
  enabled: true
  emphasis: true
"""


def _write_recipe(directory: Path, filename: str, body: str) -> Path:
    path = directory / filename
    path.write_text(body)
    return path


def test_registry_resolves_recipe_by_id(tmp_path: Path) -> None:
    _write_recipe(tmp_path, "knowledge.yaml", _VALID_YAML)
    registry = RecipeRegistry.from_directory(tmp_path)

    recipe = registry.resolve("shorts_knowledge")

    assert isinstance(recipe, ContentRecipe)
    assert recipe.id == "shorts_knowledge"


def test_registry_lists_ids(tmp_path: Path) -> None:
    _write_recipe(tmp_path, "knowledge.yaml", _VALID_YAML)
    _write_recipe(
        tmp_path,
        "general.yaml",
        _VALID_YAML.replace("shorts_knowledge", "shorts_general"),
    )
    registry = RecipeRegistry.from_directory(tmp_path)

    assert set(registry.ids()) == {"shorts_knowledge", "shorts_general"}


def test_registry_rejects_unknown_id(tmp_path: Path) -> None:
    _write_recipe(tmp_path, "knowledge.yaml", _VALID_YAML)
    registry = RecipeRegistry.from_directory(tmp_path)

    with pytest.raises(RecipeNotFoundError):
        registry.resolve("shorts_missing")


def test_registry_rejects_duplicate_ids(tmp_path: Path) -> None:
    _write_recipe(tmp_path, "a.yaml", _VALID_YAML)
    _write_recipe(tmp_path, "b.yaml", _VALID_YAML)  # same id shorts_knowledge

    with pytest.raises(ValueError, match="[Dd]uplicate"):
        RecipeRegistry.from_directory(tmp_path)


def test_registry_rejects_malformed_document(tmp_path: Path) -> None:
    _write_recipe(tmp_path, "bad.yaml", "id: broken\nstructure: []\n")

    with pytest.raises(ValueError):
        RecipeRegistry.from_directory(tmp_path)


def test_registry_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    _write_recipe(tmp_path, "list.yaml", "- not\n- a\n- mapping\n")

    with pytest.raises(ValueError):
        RecipeRegistry.from_directory(tmp_path)


# --- the five shipped shorts recipes ----------------------------------------


def test_load_shorts_recipes_has_five_expected_ids() -> None:
    registry = load_shorts_recipes()

    assert set(registry.ids()) == {
        "shorts_general",
        "shorts_story",
        "shorts_knowledge",
        "shorts_product",
        "shorts_promotional",
    }


def test_shipped_recipes_are_valid_content_recipes() -> None:
    registry = load_shorts_recipes()
    for recipe_id in registry.ids():
        recipe = registry.resolve(recipe_id)
        assert isinstance(recipe, ContentRecipe)
        assert recipe.structure  # non-empty
        assert recipe.target_duration.min_seconds <= recipe.target_duration.max_seconds


def test_no_long_form_recipes_shipped() -> None:
    registry = load_shorts_recipes()
    for recipe_id in registry.ids():
        assert recipe_id.startswith("shorts_")
        recipe = registry.resolve(recipe_id)
        # content_format, if set, must not be long-form for the shipped shorts.
        assert recipe.content_format in (None, "short")
