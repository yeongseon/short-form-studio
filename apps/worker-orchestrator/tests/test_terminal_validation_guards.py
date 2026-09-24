"""Characterize nonfatal delivery boundaries before changing execution policy."""

import pytest
from billiard.exceptions import SoftTimeLimitExceeded
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

    async def reject_claim(*_args: int | str, claim_token: str | None = None) -> None:
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


def test_timeout_after_claim_before_execution_finalizes_only_claimed_task(
    runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a delivery that owns a running task but times out resolving its run.
    case = runner_case
    original_get = case.runs.storage.get_run
    calls = 0

    async def get_run(run_id: int, workspace_id: int | None = None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SoftTimeLimitExceeded()
        return await original_get(run_id, workspace_id=workspace_id)

    monkeypatch.setattr(case.runs.storage, "get_run", get_run)
    # When the deadline fires after the exclusive claim.
    with pytest.raises(SoftTimeLimitExceeded):
        task_runner.run_task(case.delivery(), case.run_id, case.config, never_execute)
    # Then the claimed task is failed rather than stranded as running.
    tasks = run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))
    assert [task.status for task in tasks] == ["failed"]


def test_timeout_before_claim_does_not_create_task(
    runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a timeout in the initial idempotency lookup, before claim.
    case = runner_case
    before = run_in_worker_loop(case.runs.storage.get_run(case.run_id))

    async def timed_out(_task_id: str):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(case.tracking.storage, "get_by_celery_id", timed_out)
    # When the delivery times out without a claimed task.
    with pytest.raises(SoftTimeLimitExceeded):
        task_runner.run_task(case.delivery(), case.run_id, case.config, never_execute)
    # Then no task row is invented to finalize.
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id)) == []
    assert run_in_worker_loop(case.runs.storage.get_run(case.run_id)) == before


def test_timeout_in_idempotency_lookup_does_not_attempt_claim(
    runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given the deadline expires during the first lookup, before any claim.
    case = runner_case
    before = run_in_worker_loop(case.runs.storage.get_run(case.run_id))
    calls = 0
    original_lookup = case.tracking.storage.get_by_celery_id

    async def lookup(task_id: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise SoftTimeLimitExceeded()
        return await original_lookup(task_id)

    monkeypatch.setattr(case.tracking.storage, "get_by_celery_id", lookup)
    # When the delivery is processed.
    with pytest.raises(SoftTimeLimitExceeded):
        task_runner.run_task(case.delivery(), case.run_id, case.config, never_execute)
    # Then it cannot claim or mutate the run after its deadline.
    assert calls == 1
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id)) == []
    assert run_in_worker_loop(case.runs.storage.get_run(case.run_id)) == before


def test_synthetic_timeout_during_claim_does_not_execute(
    runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a synthetic delivery whose task-claim lookup hits the soft deadline.
    case = runner_case
    delivery = case.delivery()
    delivery.request.id = None
    before = run_in_worker_loop(case.runs.storage.get_run(case.run_id))

    async def timed_out(
        _run_id: int, _task_name: str, _task_id: str, *, claim_token: str | None = None,
    ):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(case.tracking, "record_task_start", timed_out)
    # When the delivery attempts to claim its task.
    with pytest.raises(SoftTimeLimitExceeded):
        task_runner.run_task(delivery, case.run_id, case.config, never_execute)
    # Then it does not execute or mutate the run.
    assert run_in_worker_loop(case.tracking.list_run_tasks(case.run_id)) == []
    assert run_in_worker_loop(case.runs.storage.get_run(case.run_id)) == before


def test_timeout_after_durable_claim_before_return_finalizes_owner(
    runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a claim committed before the storage response is interrupted.
    case = runner_case
    original_start = case.tracking.record_task_start

    async def interrupted_start(
        run_id: int, task_name: str, task_id: str, *, claim_token: str | None = None,
    ) -> None:
        await original_start(run_id, task_name, task_id, claim_token=claim_token)
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(case.tracking, "record_task_start", interrupted_start)
    # When the worker handles the soft timeout without seeing the claim response.
    with pytest.raises(SoftTimeLimitExceeded):
        task_runner.run_task(case.delivery(), case.run_id, case.config, never_execute)
    # Then the delivery it actually owns is terminal, and its run is failed.
    tracked = run_in_worker_loop(case.tracking.list_run_tasks(case.run_id))
    assert [task.status for task in tracked] == ["failed"]
    saved = run_in_worker_loop(case.runs.storage.get_run(case.run_id))
    assert (saved["current_stage"], saved["status"]) == ("FAILED", "failed")


def test_stale_stage_guard_cannot_reject_new_claim(
    runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given the original delivery loses its claim while reading the run stage.
    case = runner_case
    original_get = case.runs.storage.get_run

    async def superseded(run_id: int, workspace_id: int | None = None):
        row = await case.tracking.storage.get_by_celery_id("validation-task")
        assert row is not None
        token = row["claim_token"]
        assert isinstance(token, str)
        assert await case.tracking.mark_failed_if_claimed("validation-task", token, "INTERNAL", "retry")
        assert await case.tracking.record_task_start(
            case.run_id, case.config.task_name, "validation-task", claim_token="new-owner",
        )
        current = await original_get(run_id, workspace_id=workspace_id)
        assert current is not None
        return {**current, "current_stage": "SCRIPT_REVIEW"}

    monkeypatch.setattr(case.runs.storage, "get_run", superseded)
    # When the old delivery rejects the stage after B has claimed the task.
    with pytest.raises(task_runner.StageGuardError):
        task_runner.run_task(case.delivery(), case.run_id, case.config, never_execute)
    # Then B remains the running owner.
    row = run_in_worker_loop(case.tracking.storage.get_by_celery_id("validation-task"))
    assert row is not None
    assert (row["status"], row["claim_token"]) == ("running", "new-owner")


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
