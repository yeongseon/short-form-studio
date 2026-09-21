# pyright: reportPrivateUsage=false

"""SF-77: short-first onboarding guidance + non-empty first-draft invariants.

Locks that onboarding guides idea/duration/style/optional-assets through the
supported draft->preview->download->edit path, surfaces the four human review
gates (never bypassing them), distinguishes first-run from returning users, and
that the first draft is never an empty timeline — sample-backed when the user
supplies no assets, and feasible even for long custom durations.
"""

import pytest
from creator_domain.models import RunStage, Timeline
from creator_domain.models.duration_preset import (
    duration_preset_ids,
    resolve_custom_duration,
    resolve_duration_preset,
)
from creator_service.onboarding import (
    OnboardingGuidance,
    OnboardingStep,
    build_onboarding_first_draft,
    build_onboarding_guidance,
)
from creator_service.recipe_registry import get_recipe_registry
from creator_service.sample_project import build_sample_media_assets
from creator_service.short_template import (
    SHORT_TEMPLATES,
    SceneAsset,
    resolve_short_template,
)
from creator_service.setup_wizard import ModelCategory, evaluate_setup_state
from creator_service.timeline_compiler import compile_timeline_to_render_plan
from creator_domain.models import EncodingProfile, OutputSpec

_REGISTRY = get_recipe_registry()

_PIPELINE_APPROVAL_ORDER = (
    RunStage.SCRIPT_REVIEW,
    RunStage.VISUAL_PLAN_REVIEW,
    RunStage.VISUAL_ASSET_REVIEW,
    RunStage.FINAL_REVIEW,
)

_EXPECTED_STEPS = (
    OnboardingStep.IDEA,
    OnboardingStep.DURATION,
    OnboardingStep.STYLE,
    OnboardingStep.OPTIONAL_ASSETS,
    OnboardingStep.DRAFT,
    OnboardingStep.PREVIEW,
    OnboardingStep.DOWNLOAD,
    OnboardingStep.EDIT,
)


def _ready_setup_state():
    caps = frozenset({ModelCategory.LLM})
    return evaluate_setup_state(
        satisfied_categories=caps,
        configured_categories=caps,
        configured_providers=("openai",),
        unhealthy_providers=(),
        has_first_draft=False,
    )


def _blocked_setup_state():
    return evaluate_setup_state(
        satisfied_categories=frozenset(),
        configured_categories=frozenset(),
        configured_providers=(),
        unhealthy_providers=(),
        has_first_draft=False,
    )


# --- first-run vs returning ---


def test_first_run_when_no_existing_projects() -> None:
    guidance = build_onboarding_guidance(
        setup_state=_ready_setup_state(), has_existing_projects=False
    )
    assert isinstance(guidance, OnboardingGuidance)
    assert guidance.is_first_run is True
    assert guidance.flow == "first_run"


def test_returning_when_existing_projects() -> None:
    guidance = build_onboarding_guidance(
        setup_state=_ready_setup_state(), has_existing_projects=True
    )
    assert guidance.is_first_run is False
    assert guidance.flow == "returning"


def test_both_flows_share_the_full_supported_path() -> None:
    first = build_onboarding_guidance(
        setup_state=_ready_setup_state(), has_existing_projects=False
    )
    returning = build_onboarding_guidance(
        setup_state=_ready_setup_state(), has_existing_projects=True
    )
    assert first.steps == _EXPECTED_STEPS
    assert returning.steps == _EXPECTED_STEPS
    assert first.next_action != returning.next_action


# --- setup gate ---


def test_setup_blocked_surfaces_gate_but_still_lists_presets_and_gates() -> None:
    guidance = build_onboarding_guidance(
        setup_state=_blocked_setup_state(), has_existing_projects=False
    )
    assert guidance.duration_preset_ids == duration_preset_ids()
    assert guidance.style_template_ids == tuple(SHORT_TEMPLATES.keys())
    assert guidance.review_gates == _PIPELINE_APPROVAL_ORDER
    assert "setup" in guidance.next_action.lower() or "configure" in guidance.next_action.lower()


# --- presets / templates / gates ---


def test_guidance_exposes_registry_presets_and_templates() -> None:
    guidance = build_onboarding_guidance(
        setup_state=_ready_setup_state(), has_existing_projects=False
    )
    assert guidance.duration_preset_ids == duration_preset_ids()
    assert guidance.style_template_ids == tuple(SHORT_TEMPLATES.keys())


def test_review_gates_are_ordered_and_never_bypassed() -> None:
    from creator_domain.models import REVIEW_STAGES

    guidance = build_onboarding_guidance(
        setup_state=_ready_setup_state(), has_existing_projects=False
    )
    assert guidance.review_gates == _PIPELINE_APPROVAL_ORDER
    assert set(guidance.review_gates) == REVIEW_STAGES


def test_custom_duration_hint_is_product_level_not_a_core_clamp() -> None:
    guidance = build_onboarding_guidance(
        setup_state=_ready_setup_state(), has_existing_projects=False
    )
    assert guidance.custom_duration_hint_seconds == 180
    # No core clamp: a 200s custom duration still resolves.
    assert resolve_custom_duration(200.0).max_seconds == pytest.approx(1.1 * 200.0)


def test_guidance_is_deterministic() -> None:
    a = build_onboarding_guidance(
        setup_state=_ready_setup_state(), has_existing_projects=False
    )
    b = build_onboarding_guidance(
        setup_state=_ready_setup_state(), has_existing_projects=False
    )
    assert a == b


# --- non-empty first draft ---


def test_first_draft_is_non_empty_when_no_user_assets() -> None:
    resolved = resolve_short_template(SHORT_TEMPLATES["general"], recipe_registry=_REGISTRY)
    draft = build_onboarding_first_draft(
        resolved=resolved,
        project_id=1,
        duration=resolve_duration_preset("30"),
        scene_assets=None,
    )
    assert isinstance(draft, Timeline)
    assert len(draft.segments) >= 1


def test_first_draft_empty_sequence_behaves_like_no_assets() -> None:
    resolved = resolve_short_template(SHORT_TEMPLATES["general"], recipe_registry=_REGISTRY)
    draft = build_onboarding_first_draft(
        resolved=resolved,
        project_id=1,
        duration=resolve_duration_preset("30"),
        scene_assets=(),
    )
    assert len(draft.segments) >= 1


def test_first_draft_uses_user_assets_when_supplied() -> None:
    resolved = resolve_short_template(SHORT_TEMPLATES["general"], recipe_registry=_REGISTRY)
    user_assets = (SceneAsset(asset_id=555), SceneAsset(asset_id=556))
    # Two 2-6s segments span [4, 12]s, so a ~10s custom target is feasible for them.
    draft = build_onboarding_first_draft(
        resolved=resolved,
        project_id=1,
        duration=resolve_custom_duration(10.0),
        scene_assets=user_assets,
    )
    asset_ids = {seg.asset_id for seg in draft.segments}
    assert asset_ids == {555, 556}


def test_sample_backed_draft_compiles_to_render_plan() -> None:
    import asyncio

    resolved = resolve_short_template(SHORT_TEMPLATES["general"], recipe_registry=_REGISTRY)
    draft = build_onboarding_first_draft(
        resolved=resolved,
        project_id=1,
        duration=resolve_duration_preset("30"),
        scene_assets=None,
    )

    sample_assets = build_sample_media_assets(workspace_id=1, project_id=1)

    class _Resolver:
        def __init__(self) -> None:
            self._by_id = {a.id: a for a in sample_assets}

        async def get_asset(self, asset_id: int, workspace_id: int):
            asset = self._by_id.get(asset_id)
            if asset is None or asset.workspace_id != workspace_id:
                return None
            return asset

    plan = asyncio.run(
        compile_timeline_to_render_plan(
            draft,
            workspace_id=1,
            output_spec=OutputSpec.short_vertical(),
            encoding_profile=EncodingProfile.preview(),
            asset_resolver=_Resolver(),
        )
    )
    assert len(plan.segments) == len(draft.segments)


def test_long_custom_duration_produces_a_feasible_non_empty_draft() -> None:
    resolved = resolve_short_template(SHORT_TEMPLATES["general"], recipe_registry=_REGISTRY)
    draft = build_onboarding_first_draft(
        resolved=resolved,
        project_id=1,
        duration=resolve_custom_duration(200.0),
        scene_assets=None,
    )
    assert len(draft.segments) >= 1
    assert draft.total_duration_seconds == pytest.approx(200.0, abs=0.9 * 200.0)


def test_underlying_skeleton_still_rejects_empty_assets() -> None:
    from creator_domain.exceptions import ValidationError
    from creator_service.short_template import build_timeline_skeleton

    resolved = resolve_short_template(SHORT_TEMPLATES["general"], recipe_registry=_REGISTRY)
    with pytest.raises(ValidationError):
        build_timeline_skeleton(resolved, project_id=1, scene_assets=[])
