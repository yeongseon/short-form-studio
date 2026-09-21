"""SF-76: one-click demo Short flow — disclosure planner + normal-run seed.

The demo flow never shortcuts the supported workflow. ``build_demo_short_plan``
is a pure disclosure of readiness (from the SF-72 setup state), estimated costs
and provider requirements, and the human review approvals that gate the pipeline
— it always surfaces those four approvals so the demo cannot be read as a bypass.
``create_demo_run`` seeds only a normal ``IDEA_READY`` run from the SF-75 sample
project (no auto-advance, no auto-approve); every later transition goes through
the existing RunService / StageReviewService paths. Artifacts stay local: the
plan asserts ``external_exposure="none"`` and carries no public URL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from creator_domain.models import RunStage
from creator_service.cost_estimator import estimate_cost
from creator_service.sample_project import SampleProjectBundle
from creator_service.setup_wizard import ModelCategory, SetupState

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun
    from creator_service.run_service import RunService

# The four human review gates in pipeline order — always surfaced so the demo
# discloses required approvals instead of bypassing them.
_APPROVAL_ORDER: tuple[RunStage, ...] = (
    RunStage.SCRIPT_REVIEW,
    RunStage.VISUAL_PLAN_REVIEW,
    RunStage.VISUAL_ASSET_REVIEW,
    RunStage.FINAL_REVIEW,
)

# Canonical model set the demo's cost/provider disclosure is computed against
# (the CPU-friendly remote defaults from SF-71/SF-72).
_DEMO_MODELS: tuple[tuple[ModelCategory, str, str, str], ...] = (
    (ModelCategory.LLM, "openai", "gpt-4o-mini", "~2k in / ~2k out tokens"),
    (ModelCategory.IMAGE, "openai", "dall-e-3", "1 sample image"),
    (ModelCategory.TTS, "openai", "tts-1", "sample narration"),
)


@dataclass(frozen=True)
class ProviderRequirement:
    provider: str
    category: ModelCategory
    env_var: str


@dataclass(frozen=True)
class DemoCostLineItem:
    category: ModelCategory
    provider: str
    model_key: str
    estimated_cost_usd: float
    quantity_label: str


@dataclass(frozen=True)
class DemoShortPlan:
    ready: bool
    blocking_reasons: tuple[str, ...]
    required_provider_env_vars: tuple[ProviderRequirement, ...]
    cost_line_items: tuple[DemoCostLineItem, ...]
    estimated_total_cost_usd: float
    required_approvals: tuple[RunStage, ...]
    sample_project_id: int
    sample_timeline_id: str
    next_action: str
    external_exposure: Literal["none"]


def build_demo_short_plan(
    *,
    setup_state: SetupState,
    bundle: SampleProjectBundle,
    cost_line_items: tuple[DemoCostLineItem, ...],
) -> DemoShortPlan:
    requirements = tuple(
        ProviderRequirement(
            provider=guidance.provider,
            category=guidance.category,
            env_var=guidance.env_var,
        )
        for guidance in setup_state.env_var_guidance
    )

    blocking: list[str] = []
    if not setup_state.can_generate_first_draft:
        for category in sorted(setup_state.missing_required_categories, key=lambda c: c.value):
            env_var = next(
                (r.env_var for r in requirements if r.category == category),
                None,
            )
            suffix = f" — set {env_var}" if env_var else ""
            blocking.append(
                f"{category.value.upper()} provider is required for the demo{suffix}"
            )

    total = round(sum(item.estimated_cost_usd for item in cost_line_items), 6)

    return DemoShortPlan(
        ready=setup_state.can_generate_first_draft,
        blocking_reasons=tuple(blocking),
        required_provider_env_vars=requirements,
        cost_line_items=cost_line_items,
        estimated_total_cost_usd=total,
        required_approvals=_APPROVAL_ORDER,
        sample_project_id=bundle.project.id,
        sample_timeline_id=bundle.timeline.id,
        next_action=(
            "Create the sample-backed run and approve each review stage to render."
            if setup_state.can_generate_first_draft
            else "Configure the required provider, then start the demo."
        ),
        external_exposure="none",
    )


async def resolve_demo_short_plan(
    *,
    setup_state: SetupState,
    bundle: SampleProjectBundle,
    cost_estimator: Callable[..., float] = estimate_cost,
) -> DemoShortPlan:
    """Compute the demo's canonical cost line items, then build the pure plan."""
    image_count = sum(1 for asset in bundle.assets if asset.media_type.value == "image")
    audio_seconds = bundle.timeline.total_duration_seconds

    line_items: list[DemoCostLineItem] = []
    for category, provider, model_key, quantity_label in _DEMO_MODELS:
        if category == ModelCategory.LLM:
            cost = cost_estimator(
                provider, model_key, input_tokens=2000, output_tokens=2000
            )
        elif category == ModelCategory.IMAGE:
            cost = cost_estimator(provider, model_key, image_count=image_count)
        else:
            cost = cost_estimator(provider, model_key, audio_seconds=audio_seconds)
        line_items.append(
            DemoCostLineItem(
                category=category,
                provider=provider,
                model_key=model_key,
                estimated_cost_usd=cost,
                quantity_label=quantity_label,
            )
        )

    return build_demo_short_plan(
        setup_state=setup_state,
        bundle=bundle,
        cost_line_items=tuple(line_items),
    )


async def create_demo_run(
    *,
    run_service: RunService,
    project_id: int,
    workspace_id: int,
) -> PipelineRun:
    """Seed a normal IDEA_READY run from the sample project (no advance/approve)."""
    return await run_service.create_run(
        project_id=project_id,
        model_defaults=None,
        style_preset="demo",
        metadata={"demo": True, "sample_backed": True},
        current_stage=RunStage.IDEA_READY.value,
        status="pending",
        workspace_id=workspace_id,
    )
