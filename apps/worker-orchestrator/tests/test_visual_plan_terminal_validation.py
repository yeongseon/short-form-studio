import json

import pytest
from creator_domain.models.script_draft import ScriptSection
from creator_service.script_service import ScriptService
from creator_service.visual_plan_service import VisualPlanService
from pydantic import ValidationError
from tasks import generate_visual_plan as visual
from worker_loop import run_in_worker_loop

from .terminal_validation_support import RunnerCase, runner_case  # noqa: F401
from .terminal_postgres_support import terminal_pool as terminal_pool
from .test_generate_visual_plan import FakeEntry, FakeProvider, FakeRegistry


@pytest.mark.parametrize("length", [2000, 2001])
def test_visual_plan_output_limit_through_real_task(
    runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch, length: int,
) -> None:
    # Given the real task, script/plan services and domain parser, with only provider output controlled.
    case = runner_case
    run_in_worker_loop(case.runs.storage.update_run(case.run_id, {"current_stage": "VISUAL_PLAN_GENERATING"}))
    scripts = ScriptService()
    plans = VisualPlanService()
    run_in_worker_loop(scripts.save_draft(
        case.run_id, "edited_manually", structured_script=[ScriptSection(section_id="sec-1", type="body", text="Narration")],
    ))
    provider = FakeProvider(json.dumps([{"section_id": "sec-1", "prompt": "x" * length}]))
    registry = FakeRegistry(FakeEntry(requires_gpu=False), provider)
    monkeypatch.setattr(visual, "get_default_registry", lambda: registry)
    monkeypatch.setattr(visual, "_script_service", scripts)
    monkeypatch.setattr(visual, "_visual_plan_service", plans)
    task = visual.generate_visual_plan
    # When the decorated Celery task parses and attempts to save generated output.
    task.push_request(id="validation-task", args=(), kwargs={}, retries=0)
    try:
        if length == 2001:
            with pytest.raises(ValidationError) as raised:
                task.run(case.run_id)
            assert raised.value.errors()[0]["type"] == "string_too_long"
        else:
            task.run(case.run_id)
    finally:
        task.pop_request()
    # Then valid output is saved, invalid output fails the run without saving a partial plan.
    saved = run_in_worker_loop(case.runs.storage.get_run(case.run_id))
    plan = run_in_worker_loop(plans.get_active_plan(case.run_id))
    assert len(provider.calls) == 1
    if length == 2001:
        assert saved["current_stage"] == "FAILED"
        assert plan is None
        tracked = run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))[0]
        assert tracked.status == "failed"
        assert "x" * 100 not in (tracked.error_message or "")
    else:
        assert saved["current_stage"] == "VISUAL_PLAN_REVIEW"
        assert plan is not None and len(plan.scenes[0].prompt) == 2000
