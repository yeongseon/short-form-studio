from typing import Literal, assert_never

import anyio
import pytest
from celery.exceptions import SoftTimeLimitExceeded
from creator_domain.models import RunTask
from creator_provider.exceptions import ProviderTimeoutError, RateLimitError
from tasks import task_runner
from worker_loop import run_in_worker_loop

from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import RunnerCase, runner_case  # noqa: F401


@pytest.mark.parametrize("terminal", ["revoked", "rejected", "success"])
@pytest.mark.parametrize("outcome", [
    task_runner.TaskResult(status="success"),
    task_runner.TaskResult(status="failed"),
    ValueError("invalid output"), RuntimeError("execution failed"),
    task_runner.TaskInputError("input rejected"),
    ProviderTimeoutError("retry timeout"), RateLimitError("retry limited"),
    SoftTimeLimitExceeded(),
])
def test_terminal_decision_survives_late_worker_outcome(
    runner_case: RunnerCase,
    terminal: Literal["revoked", "rejected", "success"],
    outcome: task_runner.TaskResult | Exception,
) -> None:
    # Given an actual claimed worker paused until a terminal decision commits.
    case = runner_case
    before: list[RunTask] = []

    async def execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        entered, resume = anyio.Event(), anyio.Event()

        async def terminal_decision() -> None:
            nonlocal before
            await entered.wait()
            match terminal:
                case "revoked":
                    await case.tracking.mark_revoked("validation-task")
                case "rejected":
                    await case.tracking.mark_rejected("validation-task")
                case "success":
                    await case.tracking.mark_success("validation-task")
                case unreachable:
                    assert_never(unreachable)
            await case.runs.cancel_run(case.run_id, workspace_id=1)
            before = await case.tracking.list_run_tasks(case.run_id)
            assert before[0].status == terminal
            resume.set()

        with anyio.fail_after(10):
            async with anyio.create_task_group() as group:
                group.start_soon(terminal_decision)
                entered.set()
                await resume.wait()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    # When completion or failure arrives after the committed decision.
    if isinstance(outcome, Exception):
        with pytest.raises(type(outcome)):
            task_runner.run_task(case.delivery(), case.run_id, case.config, execute)
    else:
        result = task_runner.run_task(case.delivery(), case.run_id, case.config, execute)
        assert result["status"] == outcome.status

    # Then status, error metadata and completion timestamp remain authoritative.
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id)) == before
    saved = run_in_worker_loop(case.runs.storage.get_run(case.run_id))
    assert (saved["current_stage"], saved["status"]) == ("SCRIPT_GENERATING", "cancelled")


@pytest.mark.parametrize("outcome", ["success", "failed"])
def test_running_worker_records_ordinary_result(runner_case: RunnerCase, outcome: str) -> None:
    # Given an eligible run with no competing cancellation.
    case = runner_case

    async def execute(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        return task_runner.TaskResult(status=outcome)

    # When execution returns normally.
    result = task_runner.run_task(case.delivery(), case.run_id, case.config, execute)
    # Then both tracking and run transition to their corresponding outcome.
    tracked = run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))[0]
    saved = run_in_worker_loop(case.runs.storage.get_run(case.run_id))
    assert result["status"] == tracked.status == outcome
    assert tracked.finished_at is not None
    assert (saved["current_stage"], saved["status"]) == (
        ("SCRIPT_REVIEW", "paused") if outcome == "success" else ("FAILED", "failed")
    )
