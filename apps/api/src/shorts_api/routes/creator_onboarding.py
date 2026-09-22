"""SF-77: short-first onboarding guidance route (workspace-scoped).

Workspace-isolated via require_workspace_access (404, never 403, for
unauthorized workspaces — anti-enumeration). Read-only: it discloses the guided
draft->preview->download->edit path, duration presets, style templates, and the
human review gates; first-run vs returning is derived from workspace-scoped
project facts only.
"""

from __future__ import annotations

from creator_provider.api_keys import list_configured_providers
from creator_provider.registry import get_default_registry
from creator_service.model_health_service import ModelHealthService
from creator_service.onboarding import build_onboarding_guidance
from creator_service.project_service import project_service
from creator_service.provider_readiness import resolve_setup_provider_facts
from creator_service.setup_wizard import ModelCategory, SetupState, resolve_setup_state
from creator_service.timeline_service import timeline_service
from fastapi import APIRouter, Depends

from shorts_api.auth import CurrentUser, require_workspace_access

router = APIRouter(prefix="/workspaces", tags=["onboarding"])

_health_service = ModelHealthService()


async def _project_has_first_draft(project_id: int, workspace_id: int) -> bool:
    timeline = await timeline_service.load_timeline(
        project_id=project_id, workspace_id=workspace_id
    )
    return timeline is not None and bool(timeline.segments)


async def _workspace_has_first_draft(workspace_id: int) -> bool:
    count = await project_service.count_projects(workspace_id=workspace_id)
    if count <= 0:
        return False
    projects = await project_service.list_projects(
        limit=count, offset=0, workspace_id=workspace_id
    )
    for project in projects:
        if await _project_has_first_draft(project.id, workspace_id):
            return True
    return False


async def _onboarding_setup_state(workspace_id: int) -> SetupState:
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
        has_first_draft=await _workspace_has_first_draft(workspace_id),
    )


@router.get("/{workspace_id}/onboarding")
async def get_onboarding_guidance(
    workspace_id: int,
    _user: CurrentUser = Depends(require_workspace_access),
) -> dict[str, object]:
    setup_state = await _onboarding_setup_state(workspace_id)
    project_count = await project_service.count_projects(workspace_id=workspace_id)
    guidance = build_onboarding_guidance(
        setup_state=setup_state,
        has_existing_projects=project_count > 0,
    )
    return {
        "is_first_run": guidance.is_first_run,
        "flow": guidance.flow,
        "steps": [step.value for step in guidance.steps],
        "duration_preset_ids": list(guidance.duration_preset_ids),
        "style_template_ids": list(guidance.style_template_ids),
        "review_gates": [gate.value for gate in guidance.review_gates],
        "custom_duration_hint_seconds": guidance.custom_duration_hint_seconds,
        "next_action": guidance.next_action,
        "setup_step": guidance.setup_step.value,
        "setup_status": guidance.setup_status.value,
        "has_first_draft": guidance.has_first_draft,
    }
