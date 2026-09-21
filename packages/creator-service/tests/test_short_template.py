"""SF-63: reusable Short Templates that COMPOSE registered components.

A ShortTemplate is a lightweight composition descriptor: it references a recipe,
creative profile, output preset, and encoding preset BY ID and never copies their
fields. resolve_short_template delegates resolution to the existing registries
(RecipeRegistry, CreativeProfile.preset, OutputSpec.preset, EncodingProfile.by_name),
so there is no duplicated pipeline logic. build_timeline_skeleton produces the
initial editable Timeline draft from the resolved recipe plus caller-supplied REAL
assets: segment count is driven by how many assets fill the recipe's target
duration (recipe.structure is a narrative arc mapped proportionally across the
segments, not a fixed segment count), timing is validated at draft time, and asset
ids are preserved exactly (ownership stays with the compiler). The generated
Timeline flows unchanged through the existing compile_timeline_to_render_plan.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    ContentRecipe,
    CreativeProfile,
    EncodingProfile,
    MediaAsset,
    MediaOrigin,
    MediaType,
    OutputSpec,
    Timeline,
)
from creator_service.recipe_registry import get_recipe_registry
from creator_service.short_template import (
    SHORT_TEMPLATES,
    ResolvedShortTemplate,
    SceneAsset,
    ShortTemplate,
    build_timeline_skeleton,
    get_short_template,
    resolve_short_template,
)
from creator_service.timeline_compiler import compile_timeline_to_render_plan

_REGISTRY = get_recipe_registry()


def _resolve(template_id: str) -> ResolvedShortTemplate:
    return resolve_short_template(SHORT_TEMPLATES[template_id], recipe_registry=_REGISTRY)


def _assets(count: int, *, start_id: int = 100) -> list[SceneAsset]:
    return [SceneAsset(asset_id=start_id + i) for i in range(count)]


# ------------------------- template registry + resolution -------------------------


def test_ships_the_five_acceptance_use_case_templates() -> None:
    assert {"story", "knowledge", "educational", "product", "promotional"} <= set(SHORT_TEMPLATES)


@pytest.mark.parametrize(
    ("template_id", "recipe_id", "creative_id"),
    [
        ("story", "shorts_story", "story"),
        ("knowledge", "shorts_knowledge", "minimal"),
        ("product", "shorts_product", "product"),
        ("promotional", "shorts_promotional", "energetic"),
    ],
)
def test_resolves_each_template_to_its_registered_components(
    template_id: str, recipe_id: str, creative_id: str
) -> None:
    resolved = _resolve(template_id)
    assert isinstance(resolved, ResolvedShortTemplate)
    assert resolved.recipe.id == recipe_id
    assert resolved.creative_profile.id == creative_id
    assert resolved.output_spec == OutputSpec.short_vertical()
    assert resolved.encoding_profile == EncodingProfile.standard()


def test_educational_is_an_intentional_alias_of_the_knowledge_recipe() -> None:
    resolved = _resolve("educational")
    assert resolved.recipe.id == "shorts_knowledge"
    assert resolved.creative_profile.id == "minimal"


def test_rejects_an_unknown_template_id() -> None:
    with pytest.raises(ValidationError, match="template"):
        get_short_template("ghost")


def test_wraps_an_unknown_recipe_id_preserving_the_cause() -> None:
    template = ShortTemplate(id="bad", recipe_id="nope", creative_profile_id="story")
    with pytest.raises(ValidationError, match="recipe") as excinfo:
        resolve_short_template(template, recipe_registry=_REGISTRY)
    assert excinfo.value.__cause__ is not None


def test_wraps_an_unknown_creative_profile_id() -> None:
    template = ShortTemplate(id="bad", recipe_id="shorts_story", creative_profile_id="nope")
    with pytest.raises(ValidationError, match="creative"):
        resolve_short_template(template, recipe_registry=_REGISTRY)


def test_wraps_an_unknown_output_preset() -> None:
    template = ShortTemplate(
        id="bad", recipe_id="shorts_story", creative_profile_id="story", output_preset="nope"
    )
    with pytest.raises(ValidationError, match="output"):
        resolve_short_template(template, recipe_registry=_REGISTRY)


def test_wraps_an_unknown_encoding_preset() -> None:
    template = ShortTemplate(
        id="bad", recipe_id="shorts_story", creative_profile_id="story", encoding_preset="nope"
    )
    with pytest.raises(ValidationError, match="encoding"):
        resolve_short_template(template, recipe_registry=_REGISTRY)


# ------------------------- skeleton timing + beat mapping -------------------------


def test_skeleton_places_one_segment_per_supplied_asset() -> None:
    resolved = _resolve("story")
    assets = _assets(6)
    timeline = build_timeline_skeleton(resolved, project_id=7, scene_assets=assets)
    assert isinstance(timeline, Timeline)
    assert timeline.project_id == 7
    assert len(timeline.segments) == 6
    assert [s.asset_id for s in timeline.segments] == [a.asset_id for a in assets]


def test_skeleton_segments_are_contiguous_and_sorted() -> None:
    resolved = _resolve("story")
    timeline = build_timeline_skeleton(resolved, project_id=1, scene_assets=_assets(6))
    cursor = 0.0
    for segment in timeline.segments:
        assert segment.timeline_start_seconds == pytest.approx(cursor)
        cursor += segment.duration_seconds


def test_skeleton_segment_durations_stay_within_the_recipe_band() -> None:
    resolved = _resolve("story")
    band = resolved.recipe.visual_strategy.segment_duration
    timeline = build_timeline_skeleton(resolved, project_id=1, scene_assets=_assets(6))
    for segment in timeline.segments:
        assert band.min_seconds - 1e-6 <= segment.duration_seconds <= band.max_seconds + 1e-6


def test_skeleton_total_duration_lands_within_the_recipe_target() -> None:
    resolved = _resolve("story")
    target = resolved.recipe.target_duration
    timeline = build_timeline_skeleton(resolved, project_id=1, scene_assets=_assets(6))
    total = timeline.total_duration_seconds
    assert target.min_seconds - 1e-6 <= total <= target.max_seconds + 1e-6


def test_beats_map_proportionally_across_segments_when_more_assets_than_beats() -> None:
    # story has 5 beats; with 10 assets each beat covers a contiguous block of 2,
    # preserving the narrative arc (not cycling).
    resolved = _resolve("story")
    structure = resolved.recipe.structure
    timeline = build_timeline_skeleton(resolved, project_id=1, scene_assets=_assets(10))
    scene_ids = [s.scene_id for s in timeline.segments]
    assert scene_ids[0] == structure[0]
    assert scene_ids[-1] == structure[-1]
    # contiguous blocks, never an interleaved cycle
    first_index = {beat: scene_ids.index(beat) for beat in structure}
    assert list(first_index.values()) == sorted(first_index.values())


def test_knowledge_with_too_few_assets_fails_timing_feasibility() -> None:
    # shorts_knowledge target [30,60] cannot be filled by 4 assets at max 6s each
    # (4*6=24 < 30), so the draft is rejected rather than silently under-target.
    resolved = _resolve("knowledge")
    with pytest.raises(ValidationError, match="target duration|fill"):
        build_timeline_skeleton(resolved, project_id=1, scene_assets=_assets(4))


def test_knowledge_with_enough_assets_produces_a_valid_draft() -> None:
    resolved = _resolve("knowledge")
    target = resolved.recipe.target_duration
    timeline = build_timeline_skeleton(resolved, project_id=1, scene_assets=_assets(8))
    total = timeline.total_duration_seconds
    assert target.min_seconds - 1e-6 <= total <= target.max_seconds + 1e-6


def test_too_many_assets_overshooting_the_target_is_rejected() -> None:
    # story target max 90; 50 assets at min 2s each = 100s > 90, unfillable.
    resolved = _resolve("story")
    with pytest.raises(ValidationError, match="target duration|fill"):
        build_timeline_skeleton(resolved, project_id=1, scene_assets=_assets(50))


def test_rejects_zero_assets() -> None:
    resolved = _resolve("story")
    with pytest.raises(ValidationError, match="asset"):
        build_timeline_skeleton(resolved, project_id=1, scene_assets=[])


def test_preserves_supplied_asset_ids_exactly_and_invents_none() -> None:
    resolved = _resolve("product")
    assets = [SceneAsset(asset_id=aid) for aid in (501, 502, 503, 504, 505, 506)]
    timeline = build_timeline_skeleton(resolved, project_id=1, scene_assets=assets)
    assert [s.asset_id for s in timeline.segments] == [501, 502, 503, 504, 505, 506]


# ------------------------- composition through the real compiler -------------------------


class _FakeAssetResolver:
    def __init__(self, assets: dict[int, MediaAsset]) -> None:
        self._assets = assets

    async def get_asset(self, asset_id: int, workspace_id: int) -> MediaAsset | None:
        asset = self._assets.get(asset_id)
        if asset is None or asset.workspace_id != workspace_id:
            return None
        return asset


def _image_asset(asset_id: int, *, workspace_id: int, project_id: int) -> MediaAsset:
    return MediaAsset(
        id=asset_id,
        workspace_id=workspace_id,
        project_id=project_id,
        media_type=MediaType.IMAGE,
        origin=MediaOrigin.UPLOADED,
        storage_key=f"assets/{asset_id}.png",
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_skeleton_compiles_through_the_existing_render_plan_compiler() -> None:
    # The template layer only drafts the Timeline; compilation, asset ownership,
    # and source-bound validation remain the compiler's job (no duplication).
    resolved = _resolve("story")
    asset_ids = [201, 202, 203, 204, 205, 206]
    assets = {aid: _image_asset(aid, workspace_id=3, project_id=9) for aid in asset_ids}
    timeline = build_timeline_skeleton(
        resolved, project_id=9, scene_assets=[SceneAsset(asset_id=aid) for aid in asset_ids]
    )
    plan = await compile_timeline_to_render_plan(
        timeline,
        workspace_id=3,
        output_spec=resolved.output_spec,
        encoding_profile=resolved.encoding_profile,
        asset_resolver=_FakeAssetResolver(assets),
    )
    assert len(plan.segments) == len(asset_ids)
    assert plan.output_spec == OutputSpec.short_vertical()
