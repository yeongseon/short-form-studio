"""Synchronous delivery boundary and execution-scoped failure policy."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

from celery.exceptions import Ignore, SoftTimeLimitExceeded
from creator_provider.exceptions import ProviderTimeoutError, RateLimitError
from creator_domain.models.stage import RunStage

if TYPE_CHECKING:
    from tasks.task_runner import TaskContext, TaskResult, TaskRunnerConfig


class TaskInputError(ValueError):
    """An explicitly rejected task prerequisite or argument; keep the run editable."""


class TaskRequest(Protocol):
    retries: int


class TaskDelivery(Protocol):
    request: TaskRequest
    max_retries: int


def run_task(
    celery_self: TaskDelivery,
    run_id: int,
    config: TaskRunnerConfig,
    execute: Callable[[TaskContext], Awaitable[TaskResult]],
) -> dict[str, object]:
    """Reject invalid deliveries; apply guarded failure only after execution starts."""
    # Lazy access preserves the task_runner dependency-injection seams and re-export.
    from tasks import task_runner as runner

    request = getattr(celery_self, "request", None)
    raw_args = getattr(request, "args", None)
    raw_kwargs = getattr(request, "kwargs", None)
    if raw_args is None:
        raw_args = ()
    if raw_kwargs is None:
        raw_kwargs = {}
    if not isinstance(raw_args, (list, tuple)):
        raise ValueError(
            f"Malformed broker message: args is {type(raw_args).__name__}, expected list/tuple"
        )
    if not isinstance(raw_kwargs, dict):
        raise ValueError(
            f"Malformed broker message: kwargs is {type(raw_kwargs).__name__}, expected dict"
        )
    message = {
        "run_id": run_id,
        "task_name": config.task_name,
        "args": list(raw_args),
        "kwargs": dict(raw_kwargs),
    }
    validated_message = runner.validate_task_message(message)
    validated_run_id = validated_message["run_id"]
    task_id = str(getattr(request, "id", None) or f"run-{validated_run_id}")
    safe_failure_stages = config.safe_failure_stages or config.safe_stages
    execution_started = False

    async def execute_owned(ctx: TaskContext) -> TaskResult:
        nonlocal execution_started
        execution_started = True
        return await execute(ctx)

    try:
        return runner.run_in_worker_loop(
            runner._run_task_inner(validated_run_id, task_id, config, execute_owned)
        )
    except runner.StageGuardError:
        try:
            runner.run_in_worker_loop(runner._task_tracking_service.mark_rejected(task_id, "stage_guard"))
        except Exception:
            runner.logger.warning("Failed to record task rejection", exc_info=True)
        if config.raise_on_stage_guard:
            raise
        raise Ignore()
    except SoftTimeLimitExceeded:
        runner.logger.error("Task %s timed out for run %s", config.task_name, validated_run_id)
        try:
            runner.run_in_worker_loop(
                runner._run_service.storage.conditional_update_run(
                    validated_run_id,
                    {"current_stage": RunStage.FAILED.value, "status": "failed"},
                    expected_stages=safe_failure_stages,
                    rejected_statuses=runner._TERMINAL_STATUSES,
                )
            )
        except Exception:
            runner.logger.exception("Failed to mark run %d as FAILED after timeout", validated_run_id)
        raise
    except Ignore:
        raise
    except Exception as exc:
        if not execution_started or isinstance(exc, config.no_fail_transition_exceptions):
            try:
                code, message = runner._safe_failure_record(exc)
                runner.run_in_worker_loop(
                    runner._task_tracking_service.mark_failed(task_id, code, message)
                )
            except Exception:
                runner.logger.warning("Failed to record task failure", exc_info=True)
            raise
        if (
            isinstance(exc, (ProviderTimeoutError, RateLimitError))
            and celery_self.request.retries < celery_self.max_retries
        ):
            # Failed tracking remains reclaimable by Celery's retried delivery.
            try:
                code, message = runner._safe_failure_record(exc)
                runner.run_in_worker_loop(
                    runner._task_tracking_service.mark_failed(task_id, code, message)
                )
            except Exception:
                runner.logger.warning("Failed to mark task as failed before retry", exc_info=True)
            raise
        try:
            runner.run_in_worker_loop(
                runner._handle_general_failure(
                    task_id, validated_run_id, config.task_name, safe_failure_stages, exc,
                )
            )
        except Exception:
            runner.logger.exception("Failed error cleanup for run %d", validated_run_id)
        raise
