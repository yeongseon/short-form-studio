"""SF-76: one-click demo Short flow routes (plan disclosure + normal-run seed).

Both routes are workspace-isolated via require_project_access (404, never 403,
on unauthorized/cross-workspace access). The seed creates only a normal
IDEA_READY run; it never advances stages, approves reviews, renders, or exposes
artifacts externally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from creator_provider.api_keys import list_configured_providers
from creator_provider.registry import get_default_registry
from creator_service.demo_short_flow import (
    build_demo_short_plan,
    create_demo_run,
    resolve_demo_short_plan,
)
from creator_service.model_health_service import ModelHealthService
from creator_service.provider_readiness import resolve_setup_provider_facts
from creator_service.run_service import ConflictError, run_service
from creator_service.sample_project import build_sample_project_bundle
from creator_service.setup_wizard import ModelCategory, resolve_setup_state
from creator_service.timeline_service import timeline_service
from fastapi import APIRouter, Depends, HTTPException

from shorts_api.auth import CurrentUser, require_project_access

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


@router.post("/projects/{project_id}/demo-short/runs", status_code=201)
async def create_demo_short_run(
    project_id: int,
    access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> dict[str, object]:
    user, project = access

    if getattr(project, "status", None) == "deleting":
        raise HTTPException(
            status_code=409,
            detail="Project is being deleted; cannot create new runs",
        )

    setup_state = await _demo_setup_state(project_id, user.workspace_id)
    plan = await resolve_demo_short_plan(
        setup_state=setup_state, bundle=build_sample_project_bundle()
    )
    if not plan.ready:
        # Do not bypass the setup gate: refuse to seed until prerequisites are set.
        raise HTTPException(
            status_code=409,
            detail={"error": "demo prerequisites not configured", "plan": _plan_to_response(plan)},
        )

    try:
        run = await create_demo_run(
            run_service=run_service,
            project_id=project_id,
            workspace_id=user.workspace_id,
        )
    except ConflictError:
        raise HTTPException(
            status_code=409,
            detail="Project is being deleted; cannot create new runs",
        )

    return {"run": run.model_dump(mode="json"), "plan": _plan_to_response(plan)}
