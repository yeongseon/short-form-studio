import pytest
from tasks import task_runner
from worker_loop import run_in_worker_loop

from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import RunnerCase, runner_case  # noqa: F401


@pytest.mark.parametrize("status", ["pending", "queued", "failed", "revoked", "rejected", "success"])
@pytest.mark.parametrize("success", [False, True])
def test_worker_outcome_requires_running_predecessor(
    runner_case: RunnerCase, status: str, success: bool,
) -> None:
    # Given a task outside the worker-owned running state.
    case = runner_case
    task = run_in_worker_loop(case.tracking.storage.create_task({
        "run_id": case.run_id, "task_type": "generate_script",
        "celery_task_id": "validation-task", "status": status,
    }))
    assert task is not None
    before = run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))
    # When a late outcome tries to finalize that task.
    outcome = run_in_worker_loop(
        case.tracking.mark_success_if_running("validation-task") if success
        else case.tracking.mark_failed_if_running("validation-task", "INTERNAL", "late")
    )
    # Then the CAS misses without changing status or metadata.
    assert outcome is None
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id)) == before


def test_failed_worker_outcome_remains_reclaimable(runner_case: RunnerCase) -> None:
    # Given a failed delivery with retry budget remaining.
    from creator_provider.exceptions import ProviderTimeoutError

    case = runner_case

    async def timeout(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        raise ProviderTimeoutError("retry timeout")

    with pytest.raises(ProviderTimeoutError):
        task_runner.run_task(case.delivery(), case.run_id, case.config, timeout)
    failed = run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))[0]
    assert failed.status == "failed"

    async def complete(_ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        return task_runner.TaskResult()

    # When the actual runner receives the retry with the same task ID.
    result = task_runner.run_task(case.delivery(retries=1), case.run_id, case.config, complete)
    # Then it executes to success and clears the prior failure metadata.
    tracked = run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))[0]
    assert result["status"] == tracked.status == "success"
    assert "idempotent_skip" not in result
    assert tracked.error_code is None and tracked.error_message is None


@pytest.mark.parametrize("status", ["pending", "queued", "running"])
def test_active_task_cancellation_remains_allowed(runner_case: RunnerCase, status: str) -> None:
    # Given any active dispatch state, including a not-yet-claimed delivery.
    case = runner_case
    run_in_worker_loop(case.tracking.storage.create_task({
        "run_id": case.run_id, "task_type": "generate_script",
        "celery_task_id": "validation-task", "status": status,
    }))
    # When external cancellation is recorded.
    result = run_in_worker_loop(case.tracking.mark_revoked("validation-task"))
    # Then the active task can still be revoked.
    assert result is not None and result.status == "revoked"
