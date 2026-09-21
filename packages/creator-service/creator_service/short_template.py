"""SF-63: reusable Short Templates that COMPOSE registered components.

A ShortTemplate is a lightweight composition descriptor: it references a recipe,
creative profile, output preset, and encoding preset BY ID and never copies their
fields. resolve_short_template DELEGATES resolution to the existing registries
(RecipeRegistry, CreativeProfile.preset, OutputSpec.preset, EncodingProfile.by_name)
so there is no duplicated pipeline logic; unknown ids surface as a typed
ValidationError that preserves the registry's own error as its cause.

build_timeline_skeleton produces the initial editable Timeline draft from a
resolved recipe plus caller-supplied REAL assets. The segment count is driven by
how many assets the caller supplies to fill the recipe's target duration —
recipe.structure is a narrative arc mapped PROPORTIONALLY across the segments, not
a fixed segment count. Timing is validated at draft time (the supplied count must
be able to fill the target within the per-segment band), asset ids are preserved
exactly, and ownership/source validation stays with compile_timeline_to_render_plan.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    ContentRecipe,
    CreativeProfile,
    EncodingProfile,
    MediaSegment,
    OutputSpec,
    Timeline,
)

from creator_service.creative_profile_library import resolve_creative_profile
from creator_service.recipe_registry import RecipeNotFoundError, RecipeRegistry


@dataclass(frozen=True)
class ShortTemplate:
    id: str
    recipe_id: str
    creative_profile_id: str
    output_preset: str = "short_vertical"
    encoding_preset: str = "standard"


@dataclass(frozen=True)
class ResolvedShortTemplate:
    template_id: str
    recipe: ContentRecipe
    creative_profile: CreativeProfile
    output_spec: OutputSpec
    encoding_profile: EncodingProfile


@dataclass(frozen=True)
class SceneAsset:
    asset_id: int


def get_short_template(template_id: str) -> ShortTemplate:
    """Look up a shipped template by id; unknown ids raise a typed ValidationError."""
    template = SHORT_TEMPLATES.get(template_id)
    if template is None:
        raise ValidationError(f"unknown short template: {template_id!r}")
    return template


def resolve_short_template(
    template: ShortTemplate, *, recipe_registry: RecipeRegistry
) -> ResolvedShortTemplate:
    """Resolve a template's referenced ids to concrete components via the registries.

    Each id is resolved by the component's own registry, so this composes rather
    than duplicates. An unresolvable recipe/creative/output/encoding id is
    re-raised as a typed ValidationError that keeps the original registry error as
    its cause.
    """
    try:
        recipe = recipe_registry.resolve(template.recipe_id)
    except RecipeNotFoundError as error:
        raise ValidationError(f"unknown recipe id: {template.recipe_id!r}") from error
    creative_profile = resolve_creative_profile(template.creative_profile_id)
    try:
        output_spec = OutputSpec.preset(template.output_preset)
    except ValueError as error:
        raise ValidationError(f"unknown output preset: {template.output_preset!r}") from error
    try:
        encoding_profile = EncodingProfile.by_name(template.encoding_preset)
    except ValueError as error:
        raise ValidationError(f"unknown encoding preset: {template.encoding_preset!r}") from error
    return ResolvedShortTemplate(
        template_id=template.id,
        recipe=recipe,
        creative_profile=creative_profile,
        output_spec=output_spec,
        encoding_profile=encoding_profile,
    )


def build_timeline_skeleton(
    resolved: ResolvedShortTemplate,
    *,
    project_id: int,
    scene_assets: Sequence[SceneAsset],
) -> Timeline:
    """Draft the initial editable Timeline from a recipe plus real scene assets.

    The number of segments equals the number of supplied assets; timing is
    validated by intersecting the feasible total ``[m*seg_min, m*seg_max]`` with
    the recipe target duration, then a deterministic total (the target midpoint
    clamped into the feasible range) is distributed evenly across the segments.
    Narrative beats from recipe.structure are mapped proportionally across the
    segments. Asset ids are preserved exactly; no ownership check happens here.
    """
    recipe = resolved.recipe
    structure = recipe.structure
    if not structure:
        raise ValidationError("recipe has no narrative structure to draft from")
    count = len(scene_assets)
    if count == 0:
        raise ValidationError("at least one scene asset is required to draft a timeline")

    band = recipe.visual_strategy.segment_duration
    target = recipe.target_duration
    feasible_min = count * band.min_seconds
    feasible_max = count * band.max_seconds
    total_lo = max(feasible_min, target.min_seconds)
    total_hi = min(feasible_max, target.max_seconds)
    if total_lo > total_hi + 1e-9:
        raise ValidationError(
            f"{count} assets cannot fill the target duration "
            f"[{target.min_seconds}, {target.max_seconds}] within the per-segment band "
            f"[{band.min_seconds}, {band.max_seconds}]"
        )

    total = min(max((target.min_seconds + target.max_seconds) / 2.0, total_lo), total_hi)
    per_segment = total / count

    segments: list[MediaSegment] = []
    cursor = 0.0
    for index, scene_asset in enumerate(scene_assets):
        beat = structure[min(len(structure) - 1, math.floor(index * len(structure) / count))]
        segments.append(
            MediaSegment(
                id=f"{resolved.template_id}-seg-{index + 1}",
                scene_id=beat,
                asset_id=scene_asset.asset_id,
                timeline_start_seconds=cursor,
                duration_seconds=per_segment,
            )
        )
        cursor += per_segment

    return Timeline(id=f"{resolved.template_id}-draft", project_id=project_id, segments=segments)


SHORT_TEMPLATES: dict[str, ShortTemplate] = {
    "story": ShortTemplate(
        id="story", recipe_id="shorts_story", creative_profile_id="story"
    ),
    "knowledge": ShortTemplate(
        id="knowledge", recipe_id="shorts_knowledge", creative_profile_id="minimal"
    ),
    # "educational" is an intentional alias of the knowledge recipe: the acceptance
    # criteria name educational, but the shipped recipe that covers it is knowledge.
    "educational": ShortTemplate(
        id="educational", recipe_id="shorts_knowledge", creative_profile_id="minimal"
    ),
    "product": ShortTemplate(
        id="product", recipe_id="shorts_product", creative_profile_id="product"
    ),
    "promotional": ShortTemplate(
        id="promotional", recipe_id="shorts_promotional", creative_profile_id="energetic"
    ),
    "general": ShortTemplate(
        id="general", recipe_id="shorts_general", creative_profile_id="default"
    ),
}
