from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Literal

from creator_domain.models import RunStage
from creator_domain.models.duration_preset import duration_preset_ids
from creator_service.setup_wizard import SetupState, SetupStatus, SetupStep
from creator_service.short_template import SHORT_TEMPLATES

# The ~3 minute figure is product-level onboarding guidance only, never a core
# duration clamp (see duration_preset.resolve_custom_duration).
_CUSTOM_DURATION_HINT_SECONDS = 180

_REVIEW_GATES: tuple[RunStage, ...] = (
    RunStage.SCRIPT_REVIEW,
    RunStage.VISUAL_PLAN_REVIEW,
    RunStage.VISUAL_ASSET_REVIEW,
    RunStage.TIMELINE_REVIEW,
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
    setup_step: SetupStep
    setup_status: SetupStatus
    has_first_draft: bool


def build_onboarding_guidance(
    *,
    setup_state: SetupState,
    has_existing_projects: bool,
) -> OnboardingGuidance:
    is_first_run = not has_existing_projects
    return OnboardingGuidance(
        is_first_run=is_first_run,
        flow="first_run" if is_first_run else "returning",
        steps=_STEP_ORDER,
        duration_preset_ids=duration_preset_ids(),
        style_template_ids=tuple(SHORT_TEMPLATES.keys()),
        review_gates=_REVIEW_GATES,
        custom_duration_hint_seconds=_CUSTOM_DURATION_HINT_SECONDS,
        next_action=setup_state.next_action,
        setup_step=setup_state.step,
        setup_status=setup_state.status,
        has_first_draft=setup_state.has_first_draft,
    )
