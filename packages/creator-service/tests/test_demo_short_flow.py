# pyright: reportPrivateUsage=false

"""SF-76: one-click demo Short flow planner + seed invariants.

Locks that the demo flow discloses readiness, costs, provider requirements, and
the human review approvals of the supported workflow instead of bypassing them,
seeds only a normal IDEA_READY run from the sample project, never auto-advances
or auto-approves, and never triggers automatic external exposure.
"""

import json

import pytest
from creator_domain.models import REVIEW_STAGES, RunStage
from creator_service.demo_short_flow import (
    DemoCostLineItem,
    DemoShortPlan,
    ProviderRequirement,
    build_demo_short_plan,
    create_demo_run,
    resolve_demo_short_plan,
)
from creator_service.sample_project import (
    SAMPLE_PROJECT_ID,
    SAMPLE_WORKSPACE_ID,
    build_sample_project_bundle,
)
from creator_service.setup_wizard import ModelCategory, evaluate_setup_state
from creator_service.run_service import InMemoryRunStorage, RunService

_PIPELINE_APPROVAL_ORDER = (
    RunStage.SCRIPT_REVIEW,
    RunStage.VISUAL_PLAN_REVIEW,
    RunStage.VISUAL_ASSET_REVIEW,
    RunStage.FINAL_REVIEW,
)


def _ready_setup_state():
    all_caps = frozenset(ModelCategory)
    return evaluate_setup_state(
        satisfied_categories=all_caps,
        configured_categories=all_caps,
        configured_providers=("openai", "groq"),
        unhealthy_providers=(),
        has_first_draft=False,
    )


def _llm_only_setup_state():
    caps = frozenset({ModelCategory.LLM})
    return evaluate_setup_state(
        satisfied_categories=caps,
        configured_categories=caps,
        configured_providers=("openai",),
        unhealthy_providers=(),
        has_first_draft=False,
    )


def _no_provider_setup_state():
    return evaluate_setup_state(
        satisfied_categories=frozenset(),
        configured_categories=frozenset(),
        configured_providers=(),
        unhealthy_providers=(),
        has_first_draft=False,
    )


def _line_items() -> tuple[DemoCostLineItem, ...]:
    return (
        DemoCostLineItem(
            category=ModelCategory.LLM,
            provider="openai",
            model_key="gpt-4o-mini",
            estimated_cost_usd=0.0012,
            quantity_label="~2k in / ~2k out tokens",
        ),
        DemoCostLineItem(
            category=ModelCategory.IMAGE,
            provider="openai",
            model_key="dall-e-3",
            estimated_cost_usd=0.04,
            quantity_label="1 image",
        ),
        DemoCostLineItem(
            category=ModelCategory.TTS,
            provider="openai",
            model_key="tts-1",
            estimated_cost_usd=0.0,
            quantity_label="8s narration",
        ),
    )


def _plan(setup_state) -> DemoShortPlan:
    return build_demo_short_plan(
        setup_state=setup_state,
        bundle=build_sample_project_bundle(),
        cost_line_items=_line_items(),
    )


# --- readiness gate ---


def test_not_ready_when_llm_missing_but_approvals_still_shown() -> None:
    plan = _plan(_no_provider_setup_state())
    assert plan.ready is False
    assert any("LLM" in reason or "llm" in reason for reason in plan.blocking_reasons)
    assert any("OPENAI_API_KEY" in req.env_var for req in plan.required_provider_env_vars)
    assert plan.required_approvals == _PIPELINE_APPROVAL_ORDER


def test_ready_when_draft_prerequisites_configured() -> None:
    plan = _plan(_llm_only_setup_state())
    assert plan.ready is True
    assert plan.blocking_reasons == ()
    assert plan.next_action


def test_full_render_readiness_disclosed_separately_from_first_draft() -> None:
    plan = _plan(_llm_only_setup_state())
    assert plan.ready is True
    missing = {req.category for req in plan.required_provider_env_vars}
    assert ModelCategory.IMAGE in missing
    assert ModelCategory.TTS in missing
    assert ModelCategory.STT in missing


# --- no secrets ---


def test_plan_contains_no_secret_values() -> None:
    plan = _plan(_ready_setup_state())
    blob = json.dumps(_plan_to_jsonable(plan))
    for leak in ("sk-", "ghp_", "AKIA", "xoxb-", "password", "secret", "BEGIN PRIVATE KEY"):
        assert leak.lower() not in blob.lower()


# --- cost disclosure ---


def test_cost_line_items_and_total() -> None:
    plan = _plan(_ready_setup_state())
    assert len(plan.cost_line_items) == 3
    for item in plan.cost_line_items:
        assert item.provider
        assert item.model_key
        assert item.quantity_label
    expected_total = sum(i.estimated_cost_usd for i in _line_items())
    assert plan.estimated_total_cost_usd == pytest.approx(expected_total)


def test_zero_cost_rows_are_disclosed_not_dropped() -> None:
    plan = _plan(_ready_setup_state())
    zero_rows = [i for i in plan.cost_line_items if i.estimated_cost_usd == 0.0]
    assert any(i.category == ModelCategory.TTS for i in zero_rows)


# --- approvals never bypassed ---


def test_required_approvals_are_all_review_stages_in_pipeline_order() -> None:
    plan = _plan(_ready_setup_state())
    assert plan.required_approvals == _PIPELINE_APPROVAL_ORDER
    assert set(plan.required_approvals) == REVIEW_STAGES


def test_required_approvals_present_even_when_not_ready() -> None:
    plan = _plan(_no_provider_setup_state())
    assert plan.required_approvals == _PIPELINE_APPROVAL_ORDER


# --- sample-backed linkage ---


def test_plan_is_sample_backed() -> None:
    bundle = build_sample_project_bundle()
    plan = build_demo_short_plan(
        setup_state=_ready_setup_state(), bundle=bundle, cost_line_items=_line_items()
    )
    assert plan.sample_project_id == bundle.project.id
    assert plan.sample_timeline_id == bundle.timeline.id


# --- no automatic external exposure ---


def test_no_automatic_external_exposure() -> None:
    plan = _plan(_ready_setup_state())
    assert plan.external_exposure == "none"
    blob = json.dumps(_plan_to_jsonable(plan))
    for leak in ("http://", "https://", "localtunnel", "ngrok", "serveo"):
        assert leak not in blob


# --- determinism ---


def test_builder_is_deterministic() -> None:
    a = _plan(_ready_setup_state())
    b = _plan(_ready_setup_state())
    assert a == b


# --- resolver (injectable cost estimator) ---


@pytest.mark.asyncio
async def test_resolver_computes_line_items_via_injected_estimator() -> None:
    calls: list[tuple[str, str]] = []

    def fake_estimate(provider, model_key, **kwargs) -> float:
        calls.append((provider, model_key))
        return 0.01

    plan = await resolve_demo_short_plan(
        setup_state=_ready_setup_state(),
        bundle=build_sample_project_bundle(),
        cost_estimator=fake_estimate,
    )
    categories = {item.category for item in plan.cost_line_items}
    assert {ModelCategory.LLM, ModelCategory.IMAGE, ModelCategory.TTS} <= categories
    assert plan.estimated_total_cost_usd == pytest.approx(0.01 * len(plan.cost_line_items))
    assert len(calls) == len(plan.cost_line_items)


# --- seed creates a normal IDEA_READY run only ---


@pytest.mark.asyncio
async def test_seed_creates_normal_idea_ready_run_no_advance() -> None:
    service = RunService(InMemoryRunStorage())
    run = await create_demo_run(
        run_service=service,
        project_id=SAMPLE_PROJECT_ID,
        workspace_id=SAMPLE_WORKSPACE_ID,
    )
    assert run.current_stage == RunStage.IDEA_READY.value
    assert run.status == "pending"
    assert run.project_id == SAMPLE_PROJECT_ID
    assert run.review_stage is None


@pytest.mark.asyncio
async def test_seed_respects_deleting_project_like_normal_create() -> None:
    from creator_service.run_service import ConflictError

    storage = InMemoryRunStorage()
    storage.project_status_checker = lambda project_id: "deleting"
    service = RunService(storage)
    with pytest.raises(ConflictError):
        await create_demo_run(
            run_service=service,
            project_id=SAMPLE_PROJECT_ID,
            workspace_id=SAMPLE_WORKSPACE_ID,
        )


def _plan_to_jsonable(plan: DemoShortPlan) -> dict[str, object]:
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


def test_type_exports_exist() -> None:
    assert ProviderRequirement is not None
    assert DemoCostLineItem is not None
    assert DemoShortPlan is not None
