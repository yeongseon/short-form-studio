from dataclasses import asdict

import pytest
from creator_domain.exceptions import ConflictError
from creator_domain.models import REVIEW_STAGES, RunStage, can_transition
from creator_service.demo_short_flow import build_demo_short_plan, create_demo_run, resolve_demo_short_plan
from creator_service.run_service import InMemoryRunStorage, RunService


def test_offline_disclosure_is_deterministic_without_exposure() -> None:
    plan = build_demo_short_plan()
    assert plan == build_demo_short_plan()
    assert plan.external_exposure == "none"
    assert plan.blocking_reasons == ()
    assert plan.cost_line_items == ()
    assert plan.required_provider_env_vars == ()
    assert plan.estimated_total_cost_usd == 0
    assert plan.sample_project_id is None
    assert plan.sample_timeline_id is None
    assert set(plan.required_approvals) <= REVIEW_STAGES
    assert asdict(plan)["ready"] is True


def test_timeline_review_does_not_shortcut_legacy_gates() -> None:
    assert can_transition(RunStage.TIMELINE_REVIEW, RunStage.RENDER_GENERATING)
    for stage in (RunStage.IDEA_READY, RunStage.SCRIPT_REVIEW, RunStage.VISUAL_PLAN_REVIEW):
        assert not can_transition(stage, RunStage.TIMELINE_REVIEW)
        assert not can_transition(stage, RunStage.RENDER_GENERATING)
    assert can_transition(RunStage.RENDER_GENERATING, RunStage.FINAL_REVIEW)
    assert can_transition(RunStage.FINAL_REVIEW, RunStage.PUBLISHED)


@pytest.mark.asyncio
async def test_resolver_requires_no_provider_cost_estimation() -> None:
    assert await resolve_demo_short_plan() == build_demo_short_plan()


@pytest.mark.asyncio
async def test_seed_pauses_without_approval() -> None:
    service = RunService(InMemoryRunStorage())
    run = await create_demo_run(run_service=service, project_id=2, workspace_id=7)
    assert run.current_stage == RunStage.TIMELINE_REVIEW
    assert run.status == "paused"
    assert run.review_stage is None
    assert run.metadata == {"demo": True, "sample_backed": True, "render_source": "timeline"}


@pytest.mark.asyncio
async def test_seed_respects_deleting_project() -> None:
    storage = InMemoryRunStorage()
    storage.project_status_checker = lambda project_id: "deleting"
    with pytest.raises(ConflictError):
        await create_demo_run(run_service=RunService(storage), project_id=2, workspace_id=7)
