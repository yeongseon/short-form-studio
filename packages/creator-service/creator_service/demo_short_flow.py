"""Offline sample disclosure and its explicitly reviewed timeline run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from creator_domain.models import PipelineRun, RunStage
from creator_service.run_service import RunService
from creator_service.setup_wizard import ModelCategory


@dataclass(frozen=True, slots=True)
class ProviderRequirement:
    provider: str
    category: ModelCategory
    env_var: str


@dataclass(frozen=True, slots=True)
class DemoCostLineItem:
    category: ModelCategory
    provider: str
    model_key: str
    estimated_cost_usd: float
    quantity_label: str


@dataclass(frozen=True, slots=True)
class DemoShortPlan:
    ready: bool
    blocking_reasons: tuple[str, ...]
    required_provider_env_vars: tuple[ProviderRequirement, ...]
    cost_line_items: tuple[DemoCostLineItem, ...]
    estimated_total_cost_usd: float
    required_approvals: tuple[RunStage, ...]
    sample_project_id: int | None
    sample_timeline_id: str | None
    next_action: str
    external_exposure: Literal["none"]


def build_demo_short_plan() -> DemoShortPlan:
    return DemoShortPlan(
        ready=True,
        blocking_reasons=(),
        required_provider_env_vars=(),
        cost_line_items=(),
        estimated_total_cost_usd=0.0,
        required_approvals=(RunStage.TIMELINE_REVIEW, RunStage.FINAL_REVIEW),
        sample_project_id=None,
        sample_timeline_id=None,
        next_action="Create the offline sample, preview its timeline, then approve rendering.",
        external_exposure="none",
    )


async def resolve_demo_short_plan() -> DemoShortPlan:
    return build_demo_short_plan()


async def create_demo_run(
    *, run_service: RunService, project_id: int, workspace_id: int,
) -> PipelineRun:
    return await run_service.create_run(
        project_id=project_id,
        model_defaults=None,
        style_preset="demo",
        metadata={"demo": True, "sample_backed": True, "render_source": "timeline"},
        current_stage=RunStage.TIMELINE_REVIEW.value,
        status="paused",
        workspace_id=workspace_id,
    )
