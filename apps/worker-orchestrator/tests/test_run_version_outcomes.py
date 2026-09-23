from creator_domain.models import PipelineRun
from tasks import task_runner
from worker_loop import run_in_worker_loop

from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import RunnerCase, runner_case as runner_case


def test_actual_runner_preserves_cancel_and_invalidates_old_version(runner_case: RunnerCase) -> None:
    # Given actual runner execution that observes cancellation before completion.
    case = runner_case
    snapshots: list[PipelineRun] = []

    async def execute(ctx: task_runner.TaskContext) -> task_runner.TaskResult:
        snapshots.append(await case.runs.cancel_run(ctx.run_id, workspace_id=1))
        return task_runner.TaskResult()

    # When the real runner reaches its guarded success transition.
    task_runner.run_task(case.delivery(), case.run_id, case.config, execute)
    # Then the existing terminal guard preserves cancellation without another increment.
    saved = run_in_worker_loop(case.runs.get_run(case.run_id, workspace_id=1))
    assert saved == snapshots[0]
    assert saved is not None
    assert (saved.status, saved.current_stage, saved.version) == ("cancelled", "SCRIPT_GENERATING", 1)
    assert run_in_worker_loop(case.runs.storage.update_run(
        case.run_id, {"status": "completed"}, workspace_id=1, expected_version=0,
    )) is None
