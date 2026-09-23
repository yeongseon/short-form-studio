import pytest
from creator_domain.exceptions import ValidationError as DomainValidationError
from creator_domain.models.visual_plan import VisualScene
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_service.actionable_errors import failure_summary_from_code
from pydantic import ValidationError
from tasks import task_runner
from worker_loop import run_in_worker_loop

from .terminal_validation_support import RunnerCase, runner_case  # noqa: F401
from .terminal_postgres_support import terminal_pool as terminal_pool


def invalid_scene() -> VisualScene:
    return VisualScene(
        scene_id="scene-1", section_id="sec-1", scene_index=0,
        section_type="body", original_text="text", prompt="x" * 2001,
    )


@pytest.mark.parametrize("error", [
    ValueError("invalid execution token=private-value"),
    DomainValidationError("invalid domain input token=private-value"),
    RuntimeError("execution failed token=private-value"),
    ProviderError("provider failed token=private-value"),
    ProviderTimeoutError("timeout"), RateLimitError("limited"),
])
def test_terminal_execution_error_fails_eligible_run(runner_case: RunnerCase, error: Exception) -> None:
    # Given a real runner and stores with exhausted retry budget.
    case = runner_case

    async def execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        raise error

    # When an execution error escapes.
    with pytest.raises(type(error)):
        task_runner.run_task(case.delivery(retries=2), case.run_id, case.config, execute)
    # Then the task and eligible run are failed with a safe recoverable summary.
    saved = run_in_worker_loop(case.runs.storage.get_run(case.run_id))
    assert (saved["current_stage"], saved["status"]) == ("FAILED", "failed")
    tracked = run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))[0]
    assert tracked.status == "failed"
    assert "private-value" not in (tracked.error_message or "")
    summary = failure_summary_from_code(tracked.error_code)
    assert summary is not None and summary["recovery_steps"]


def test_pydantic_execution_validation_fails_run(runner_case: RunnerCase) -> None:
    # Given a generating run whose output exceeds the real domain prompt limit.
    case = runner_case

    async def execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        invalid_scene()
        return task_runner.TaskResult()

    # When Pydantic rejects the generated scene.
    with pytest.raises(ValidationError) as raised:
        task_runner.run_task(case.delivery(), case.run_id, case.config, execute)
    # Then the actual string-length validation fails both task and eligible run.
    assert raised.value.errors()[0]["type"] == "string_too_long"
    assert run_in_worker_loop(case.runs.storage.get_run(case.run_id))["current_stage"] == "FAILED"
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))[0].status == "failed"


@pytest.mark.parametrize("stage,status", [
    ("SCRIPT_GENERATING", "cancelled"), ("SCRIPT_REVIEW", "paused"),
    ("PUBLISHED", "completed"), ("FINAL_REVIEW", "completed"),
])
@pytest.mark.parametrize("error", [ValueError("invalid"), RuntimeError("failed")])
def test_late_failure_preserves_concurrent_run_state(
    runner_case: RunnerCase, stage: str, status: str, error: Exception,
) -> None:
    # Given cancellation or advancement during an owned execution.
    case = runner_case

    async def execute(ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        await case.runs.storage.update_run(ctx.run_id, {"current_stage": stage, "status": status})
        raise error

    # When the old task fails after that state change.
    with pytest.raises(type(error)):
        task_runner.run_task(case.delivery(), case.run_id, case.config, execute)
    # Then guarded failure never overwrites the newer run state.
    saved = run_in_worker_loop(case.runs.storage.get_run(case.run_id))
    assert (saved["current_stage"], saved["status"]) == (stage, status)


@pytest.mark.parametrize("valid_output", [False, True])
def test_redelivery_recovers_failed_task_generating_run(runner_case: RunnerCase, valid_output: bool) -> None:
    # Given the legacy inconsistent record, explicitly redelivered with its original payload.
    case = runner_case
    run_in_worker_loop(case.tracking.record_task_start(case.run_id, "generate_script", "validation-task"))
    run_in_worker_loop(case.tracking.mark_failed("validation-task", "INTERNAL", "legacy failure"))

    async def execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        if not valid_output:
            invalid_scene()
        return task_runner.TaskResult()

    # When redelivery reclaims and executes, rather than blindly failing the old record.
    if valid_output:
        task_runner.run_task(case.delivery(), case.run_id, case.config, execute)
    else:
        with pytest.raises(ValidationError):
            task_runner.run_task(case.delivery(), case.run_id, case.config, execute)
    # Then fresh execution determines recovery; the old failure is not authoritative.
    saved = run_in_worker_loop(case.runs.storage.get_run(case.run_id))
    assert saved["current_stage"] == ("SCRIPT_REVIEW" if valid_output else "FAILED")
