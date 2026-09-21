"""Registry that loads and resolves ContentRecipe definitions from YAML.

Recipes live under ``recipes/shorts/*.yaml`` and are resolved by their explicit
``id``. Long-form recipes are intentionally not shipped (short-first product).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from creator_domain.models import ContentRecipe
from pydantic import ValidationError


class RecipeNotFoundError(KeyError):
    """Raised when a recipe id is not registered."""


def _load_recipe_file(path: Path) -> ContentRecipe:
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML in {path.name}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"Recipe {path.name} must be a mapping, got {type(raw).__name__}")
    try:
        return ContentRecipe.model_validate(raw)
    except ValidationError as error:
        raise ValueError(f"Invalid recipe {path.name}: {error}") from error


class RecipeRegistry:
    """An immutable, id-indexed collection of ContentRecipes."""

    def __init__(self, recipes: dict[str, ContentRecipe]) -> None:
        self._recipes = dict(recipes)

    @classmethod
    def from_directory(cls, directory: Path | str) -> RecipeRegistry:
        """Load every ``*.yaml`` recipe in *directory*, rejecting duplicate ids."""
        base = Path(directory)
        recipes: dict[str, ContentRecipe] = {}
        for path in sorted(base.glob("*.yaml")):
            recipe = _load_recipe_file(path)
            if recipe.id in recipes:
                raise ValueError(f"Duplicate recipe id: {recipe.id!r} (in {path.name})")
            recipes[recipe.id] = recipe
        return cls(recipes)

    def resolve(self, recipe_id: str) -> ContentRecipe:
        try:
            return self._recipes[recipe_id]
        except KeyError as error:
            raise RecipeNotFoundError(f"Unknown recipe id: {recipe_id!r}") from error

    def ids(self) -> list[str]:
        return sorted(self._recipes)

    def __contains__(self, recipe_id: object) -> bool:
        return recipe_id in self._recipes


def _shorts_recipe_dir() -> Path:
    # recipes/shorts lives at the repository root, three parents up from this
    # module (packages/creator-service/creator_service/recipe_registry.py).
    return Path(__file__).resolve().parents[3] / "recipes" / "shorts"


def load_shorts_recipes(directory: Path | str | None = None) -> RecipeRegistry:
    """Load the shipped short-form recipes from ``recipes/shorts``."""
    base = Path(directory) if directory is not None else _shorts_recipe_dir()
    return RecipeRegistry.from_directory(base)


_registry: RecipeRegistry | None = None


def get_recipe_registry() -> RecipeRegistry:
    """Return a lazily-loaded singleton registry of the shipped recipes."""
    global _registry  # noqa: PLW0603
    if _registry is None:
        _registry = load_shorts_recipes()
    return _registry
