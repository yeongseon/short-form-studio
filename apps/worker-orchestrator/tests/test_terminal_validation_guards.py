"""Characterize nonfatal delivery boundaries before changing execution policy."""

import pytest
from celery.exceptions import Ignore
from creator_provider.exceptions import ProviderTimeoutError, RateLimitError
from tasks import task_runner
from worker_loop import run_in_worker_loop

from .terminal_validation_support import RunnerCase, runner_case  # noqa: F401
from .terminal_postgres_support import terminal_pool as terminal_pool


async def never_execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
    pytest.fail("rejected or duplicate delivery executed")


@pytest.mark.parametrize("kwargs", [{"model_key": "unknown-model"}, {"prompt": "x" * 5000}])
def test_invalid_broker_input_preserves_run(runner_case: RunnerCase, kwargs: dict[str, str]) -> None:
    # Given a generating run referenced by a malformed broker message.
    case = runner_case
    delivery = case.delivery()
    delivery.request.kwargs = kwargs
    before = run_in_worker_loop(case.runs.storage.get_run(case.run_id))
    # When validation rejects the delivery before claim.
    with pytest.raises(ValueError):
        task_runner.run_task(delivery, case.run_id, case.config, never_execute)
    # Then neither the run nor task tracking is mutated.
    assert run_in_worker_loop(case.runs.storage.get_run(case.run_id)) == before
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id)) == []


@pytest.mark.parametrize("stage,status", [
    ("SCRIPT_REVIEW", "paused"), ("PUBLISHED", "completed"),
    ("SCRIPT_GENERATING", "cancelled"), ("unknown-stage", "running"),
])
def test_stage_rejection_preserves_run(runner_case: RunnerCase, stage: str, status: str) -> None:
    # Given a cancelled, advanced or invalid-stage run.
    case = runner_case
    before = run_in_worker_loop(case.runs.storage.update_run(
        case.run_id, {"current_stage": stage, "status": status},
    ))
    # When a stale delivery arrives.
    with pytest.raises(task_runner.StageGuardError):
        task_runner.run_task(case.delivery(), case.run_id, case.config, never_execute)
    # Then stage rejection does not fail the run.
    assert run_in_worker_loop(case.runs.storage.get_run(case.run_id)) == before
    assert [t.status for t in run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))] == ["rejected"]


@pytest.mark.parametrize("completed", [False, True])
def test_duplicate_delivery_preserves_claimed_work(runner_case: RunnerCase, completed: bool) -> None:
    # Given a task claimed by another delivery or already successful.
    case = runner_case
    run_in_worker_loop(case.tracking.record_task_start(case.run_id, "generate_script", "validation-task"))
    if completed:
        run_in_worker_loop(case.tracking.mark_success("validation-task"))
    before = run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))
    # When the duplicate is delivered.
    result = task_runner.run_task(case.delivery(), case.run_id, case.config, never_execute)
    # Then it skips execution without modifying the existing task.
    assert result["idempotent_skip"] is True
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id)) == before


@pytest.mark.parametrize("error", [ProviderTimeoutError("timeout"), RateLimitError("limited")])
def test_retryable_error_preserves_generating_run(runner_case: RunnerCase, error: Exception) -> None:
    # Given a claimed task with retry budget remaining.
    case = runner_case

    async def execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        raise error

    # When a retryable provider error escapes execution.
    with pytest.raises(type(error)):
        task_runner.run_task(case.delivery(), case.run_id, case.config, execute)
    # Then the task is reclaimable while the run remains generating.
    assert run_in_worker_loop(case.runs.storage.get_run(case.run_id))["current_stage"] == "SCRIPT_GENERATING"
    assert [t.status for t in run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))] == ["failed"]


def test_claim_validation_error_preserves_run(runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a validation failure while recording the task start, before execution.
    case = runner_case
    before = run_in_worker_loop(case.runs.storage.get_run(case.run_id))

    async def reject_claim(*_args: int | str) -> None:
        raise ValueError("invalid tracking row")

    monkeypatch.setattr(case.tracking, "record_task_start", reject_claim)
    # When the claim fails.
    with pytest.raises(ValueError):
        task_runner.run_task(case.delivery(), case.run_id, case.config, never_execute)
    # Then an unclaimed delivery cannot fail the run.
    assert run_in_worker_loop(case.runs.storage.get_run(case.run_id)) == before
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id)) == []


def test_shutdown_preserves_run(runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given graceful shutdown before claim.
    case = runner_case
    monkeypatch.setattr("celery_app.is_shutting_down", lambda: True)
    before = run_in_worker_loop(case.runs.storage.get_run(case.run_id))
    # When a new delivery arrives.
    with pytest.raises(Ignore):
        task_runner.run_task(case.delivery(), case.run_id, case.config, never_execute)
    # Then no work is started and the run is unchanged.
    assert run_in_worker_loop(case.runs.storage.get_run(case.run_id)) == before
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id)) == []


@pytest.mark.parametrize("task_name,stage,kwargs", [
    ("generate_audio", "AUDIO_GENERATING", {}),
    ("generate_visual_plan", "VISUAL_PLAN_GENERATING", {}),
    ("generate_scene_image", "VISUAL_ASSET_GENERATING", {}),
    ("generate_subtitles", "SUBTITLE_GENERATING", {"subtitle_format": "invalid"}),
    ("generate_paragraph_subtitles", "SUBTITLE_GENERATING", {"section_id": "sec-1", "subtitle_format": "invalid"}),
    ("generate_paragraph_audio", "AUDIO_GENERATING", {"section_id": "missing"}),
])
def test_missing_or_invalid_task_input_preserves_run(
    runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch,
    task_name: str, stage: str, kwargs: dict[str, str],
) -> None:
    import importlib
    from creator_service.script_service import ScriptService
    from creator_service.visual_plan_service import VisualPlanService

    # Given a real task with missing prerequisites or an invalid requested format.
    case = runner_case
    module = importlib.import_module(f"tasks.{task_name}")
    if hasattr(module, "_script_service"):
        monkeypatch.setattr(module, "_script_service", ScriptService())
    if hasattr(module, "_visual_plan_service"):
        monkeypatch.setattr(module, "_visual_plan_service", VisualPlanService())
    before = run_in_worker_loop(case.runs.storage.update_run(case.run_id, {"current_stage": stage}))
    task = getattr(module, task_name)
    # When the actual task rejects that input before making provider calls.
    task.push_request(id="validation-task", args=(), kwargs={}, retries=0)
    try:
        with pytest.raises(ValueError):
            task.run(case.run_id, **kwargs)
    finally:
        task.pop_request()
    # Then the task failure is visible while the run remains usable for corrected input.
    assert run_in_worker_loop(case.runs.storage.get_run(case.run_id)) == before
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))[0].status == "failed"
