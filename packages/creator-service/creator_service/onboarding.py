"""SF-77: short-first onboarding guidance and a never-empty first draft.

build_onboarding_guidance is a pure disclosure (facts in) of the guided
idea->duration->style->optional-assets->draft->preview->download->edit path, the
duration presets and style templates to choose from, and the four human review
gates that must be honored (never bypassed). It distinguishes first-run from
returning users by whether the workspace already has projects.

build_onboarding_first_draft guarantees a non-empty starting Timeline: when the
user supplies no assets it fills the requested duration with repeated sample
(license-clean, synthetic) scene assets, computing a feasible placeholder count
so even long custom durations draft successfully. It wraps build_timeline_skeleton
without weakening that primitive's "at least one asset" contract.
"""

from __future__ import annotations

import dataclasses
import enum
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from creator_domain.models import RunStage
from creator_domain.models.content_recipe import DurationRange
from creator_domain.models.duration_preset import duration_preset_ids
from creator_domain.models.timeline import Timeline
from creator_service.sample_project import build_sample_media_assets
from creator_service.setup_wizard import SetupState
from creator_service.short_template import (
    SHORT_TEMPLATES,
    ResolvedShortTemplate,
    SceneAsset,
    build_timeline_skeleton,
)

# The ~3 minute figure is product-level onboarding guidance only, never a core
# duration clamp (see duration_preset.resolve_custom_duration).
_CUSTOM_DURATION_HINT_SECONDS = 180

# The four human review gates in pipeline order — always surfaced so onboarding
# discloses the approvals it routes through instead of bypassing them.
_REVIEW_GATES: tuple[RunStage, ...] = (
    RunStage.SCRIPT_REVIEW,
    RunStage.VISUAL_PLAN_REVIEW,
    RunStage.VISUAL_ASSET_REVIEW,
    RunStage.FINAL_REVIEW,
)


class OnboardingStep(enum.Enum):
    IDEA = "idea"
    DURATION = "duration"
    STYLE = "style"
    OPTIONAL_ASSETS = "optional_assets"
    DRAFT = "draft"
    PREVIEW = "preview"
    DOWNLOAD = "download"
    EDIT = "edit"


_STEP_ORDER: tuple[OnboardingStep, ...] = (
    OnboardingStep.IDEA,
    OnboardingStep.DURATION,
    OnboardingStep.STYLE,
    OnboardingStep.OPTIONAL_ASSETS,
    OnboardingStep.DRAFT,
    OnboardingStep.PREVIEW,
    OnboardingStep.DOWNLOAD,
    OnboardingStep.EDIT,
)


@dataclass(frozen=True)
class OnboardingGuidance:
    is_first_run: bool
    flow: Literal["first_run", "returning"]
    steps: tuple[OnboardingStep, ...]
    duration_preset_ids: tuple[str, ...]
    style_template_ids: tuple[str, ...]
    review_gates: tuple[RunStage, ...]
    custom_duration_hint_seconds: int
    next_action: str


def build_onboarding_guidance(
    *,
    setup_state: SetupState,
    has_existing_projects: bool,
) -> OnboardingGuidance:
    is_first_run = not has_existing_projects
    if not setup_state.can_generate_first_draft:
        next_action = "Configure the required provider in setup, then start your first Short."
    elif is_first_run:
        next_action = "Start your first Short: pick an idea, duration, and style to draft."
    else:
        next_action = "Start a new Short or continue editing an existing draft."

    return OnboardingGuidance(
        is_first_run=is_first_run,
        flow="first_run" if is_first_run else "returning",
        steps=_STEP_ORDER,
        duration_preset_ids=duration_preset_ids(),
        style_template_ids=tuple(SHORT_TEMPLATES.keys()),
        review_gates=_REVIEW_GATES,
        custom_duration_hint_seconds=_CUSTOM_DURATION_HINT_SECONDS,
        next_action=next_action,
    )


def _feasible_placeholder_count(*, duration: DurationRange, band: DurationRange) -> int:
    # build_timeline_skeleton needs count*seg_min <= target and count*seg_max >= target
    # to intersect; pick the smallest count whose feasible max reaches the target min.
    nominal = (duration.min_seconds + duration.max_seconds) / 2.0
    count = math.ceil(nominal / band.max_seconds)
    return max(count, 1)


def build_onboarding_first_draft(
    *,
    resolved: ResolvedShortTemplate,
    project_id: int,
    duration: DurationRange,
    scene_assets: Sequence[SceneAsset] | None,
) -> Timeline:
    recipe = resolved.recipe.model_copy(update={"target_duration": duration})
    tuned = dataclasses.replace(resolved, recipe=recipe)

    if scene_assets:
        return build_timeline_skeleton(
            tuned, project_id=project_id, scene_assets=list(scene_assets)
        )

    band = recipe.visual_strategy.segment_duration
    count = _feasible_placeholder_count(duration=duration, band=band)
    sample_asset_ids = [asset.id for asset in build_sample_media_assets()]
    placeholders = [
        SceneAsset(asset_id=sample_asset_ids[index % len(sample_asset_ids)])
        for index in range(count)
    ]
    return build_timeline_skeleton(
        tuned, project_id=project_id, scene_assets=placeholders
    )
