"""SF-76 + P0-3: one-click demo Short flow routes.

GET /projects/{id}/demo-short/plan is a pure, project-scoped disclosure (costs,
required approvals, readiness) via require_project_access — it persists nothing.
POST /workspaces/{id}/demo-short/runs is workspace-scoped via
require_workspace_access because it CREATES a new workspace-owned "Demo Short"
project (real sample-backed assets + timeline) and a normal IDEA_READY run; it
never mutates an existing project, advances stages, approves reviews, or exposes
artifacts externally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from creator_provider.api_keys import list_configured_providers
from creator_provider.registry import get_default_registry
from creator_service.demo_seed import seed_demo_short
from creator_service.demo_short_flow import (
    build_demo_short_plan,
    resolve_demo_short_plan,
)
from creator_service.media_asset_service import media_asset_service
from creator_service.model_health_service import ModelHealthService
from creator_service.project_service import project_service
from creator_service.provider_readiness import resolve_setup_provider_facts
from creator_service.run_service import run_service
from creator_service.sample_project import build_sample_project_bundle
from creator_service.setup_wizard import ModelCategory, resolve_setup_state
from creator_service.timeline_service import timeline_service
from fastapi import APIRouter, Depends, HTTPException

from shorts_api.auth import CurrentUser, require_project_access, require_workspace_access

if TYPE_CHECKING:
    from creator_domain.models.project import Project

router = APIRouter(tags=["demo"])

_health_service = ModelHealthService()


async def _project_has_first_draft(project_id: int, workspace_id: int) -> bool:
    timeline = await timeline_service.load_timeline(
        project_id=project_id, workspace_id=workspace_id
    )
    return timeline is not None and bool(timeline.segments)


async def _demo_setup_state(project_id: int, workspace_id: int):
    facts = await resolve_setup_provider_facts(
        registry=get_default_registry(),
        health_service=_health_service,
        configured_remote_providers=list_configured_providers(),
    )

    async def _category_status() -> dict[ModelCategory, tuple[str, ...]]:
        return facts.category_status

    async def _unhealthy() -> tuple[str, ...]:
        return facts.unhealthy_providers

    return await resolve_setup_state(
        configured_providers_source=lambda: list(facts.configured_providers),
        category_status_source=_category_status,
        unhealthy_source=_unhealthy,
        has_first_draft=await _project_has_first_draft(project_id, workspace_id),
    )


async def _workspace_demo_setup_state(workspace_id: int):
    # The seed route creates the first draft itself, so readiness only needs the
    # required providers configured — has_first_draft stays False honestly.
    facts = await resolve_setup_provider_facts(
        registry=get_default_registry(),
        health_service=_health_service,
        configured_remote_providers=list_configured_providers(),
    )

    async def _category_status() -> dict[ModelCategory, tuple[str, ...]]:
        return facts.category_status

    async def _unhealthy() -> tuple[str, ...]:
        return facts.unhealthy_providers

    return await resolve_setup_state(
        configured_providers_source=lambda: list(facts.configured_providers),
        category_status_source=_category_status,
        unhealthy_source=_unhealthy,
        has_first_draft=False,
    )


def _plan_to_response(plan: object) -> dict[str, object]:
    from creator_service.demo_short_flow import DemoShortPlan

    assert isinstance(plan, DemoShortPlan)
    return {
        "ready": plan.ready,
        "blocking_reasons": list(plan.blocking_reasons),
        "required_provider_env_vars": [
            {"provider": r.provider, "category": r.category.value, "env_var": r.env_var}
            for r in plan.required_provider_env_vars
        ],
        "cost_line_items": [
            {
                "category": i.category.value,
                "provider": i.provider,
                "model_key": i.model_key,
                "estimated_cost_usd": i.estimated_cost_usd,
                "quantity_label": i.quantity_label,
            }
            for i in plan.cost_line_items
        ],
        "estimated_total_cost_usd": plan.estimated_total_cost_usd,
        "required_approvals": [s.value for s in plan.required_approvals],
        "sample_project_id": plan.sample_project_id,
        "sample_timeline_id": plan.sample_timeline_id,
        "next_action": plan.next_action,
        "external_exposure": plan.external_exposure,
    }


@router.get("/projects/{project_id}/demo-short/plan")
async def get_demo_short_plan(
    project_id: int,
    access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> dict[str, object]:
    user, _ = access
    setup_state = await _demo_setup_state(project_id, user.workspace_id)
    plan = await resolve_demo_short_plan(
        setup_state=setup_state,
        bundle=build_sample_project_bundle(),
    )
    return _plan_to_response(plan)


@router.post("/workspaces/{workspace_id}/demo-short/runs", status_code=201)
async def create_demo_short_run(
    workspace_id: int,
    _user: CurrentUser = Depends(require_workspace_access),
) -> dict[str, object]:
    # The demo creates a NEW workspace-owned "Demo Short" project (it does not
    # mutate a user's existing project), so the route is workspace-scoped.
    setup_state = await _workspace_demo_setup_state(workspace_id)
    plan = await resolve_demo_short_plan(
        setup_state=setup_state, bundle=build_sample_project_bundle()
    )
    if not plan.ready:
        # Do not bypass the setup gate: refuse to seed until prerequisites are set.
        raise HTTPException(
            status_code=409,
            detail={"error": "demo prerequisites not configured", "plan": _plan_to_response(plan)},
        )

    result = await seed_demo_short(
        workspace_id=workspace_id,
        project_service=project_service,
        media_asset_service=media_asset_service,
        timeline_service=timeline_service,
        run_service=run_service,
    )

    return {
        "run": result.run.model_dump(mode="json"),
        "seeded_project_id": result.project_id,
        "timeline_id": result.timeline_id,
        "plan": _plan_to_response(plan),
    }
