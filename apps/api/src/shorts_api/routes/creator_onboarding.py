"""SF-77: short-first onboarding guidance route (workspace-scoped).

Workspace-isolated via require_workspace_access (404, never 403, for
unauthorized workspaces — anti-enumeration). Read-only: it discloses the guided
draft->preview->download->edit path, duration presets, style templates, and the
human review gates; first-run vs returning is derived from workspace-scoped
project facts only.
"""

from __future__ import annotations

from creator_provider.api_keys import list_configured_providers
from creator_service.onboarding import build_onboarding_guidance
from creator_service.project_service import project_service
from creator_service.setup_wizard import ModelCategory, resolve_setup_state
from fastapi import APIRouter, Depends

from shorts_api.auth import CurrentUser, require_workspace_access

router = APIRouter(prefix="/workspaces", tags=["onboarding"])

# Provider -> capability categories it can satisfy (names only, never key values).
_PROVIDER_CATEGORIES: dict[str, tuple[ModelCategory, ...]] = {
    "openai": (ModelCategory.LLM, ModelCategory.IMAGE, ModelCategory.TTS),
    "anthropic": (ModelCategory.LLM,),
    "google": (ModelCategory.LLM, ModelCategory.IMAGE),
    "stability": (ModelCategory.IMAGE,),
    "elevenlabs": (ModelCategory.TTS,),
    "groq": (ModelCategory.STT,),
}


async def _onboarding_setup_state():
    configured = list_configured_providers()

    async def _category_status() -> dict[ModelCategory, tuple[str, ...]]:
        status: dict[ModelCategory, list[str]] = {}
        for provider in configured:
            for category in _PROVIDER_CATEGORIES.get(provider, ()):
                status.setdefault(category, []).append(provider)
        return {category: tuple(providers) for category, providers in status.items()}

    async def _unhealthy() -> tuple[str, ...]:
        return ()

    return await resolve_setup_state(
        configured_providers_source=lambda: list(configured),
        category_status_source=_category_status,
        unhealthy_source=_unhealthy,
        has_first_draft=False,
    )


@router.get("/{workspace_id}/onboarding")
async def get_onboarding_guidance(
    workspace_id: int,
    _user: CurrentUser = Depends(require_workspace_access),
) -> dict[str, object]:
    setup_state = await _onboarding_setup_state()
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
    }
