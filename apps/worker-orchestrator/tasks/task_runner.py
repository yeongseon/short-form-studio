"""Common task runner infrastructure for Celery worker tasks.

Extracts cross-cutting concerns shared by all generation tasks:
- Task tracking (start, running, success, failed, rejected)
- Stage guard validation
- Workspace/project context resolution
- GPU lock acquisition/release
- Provider usage recording
- Conditional stage transitions (success/failure)
- Active task ID cleanup

Usage:
    @celery_app.task(bind=True, ...)
    @trace_task("generate_foo")
    def generate_foo(self, run_id: int, ...) -> dict[str, object]:
        config = TaskRunnerConfig(
            task_name="generate_foo",
            allowed_stages=frozenset({RunStage.FOO_GENERATING}),
            safe_stages=frozenset({RunStage.FOO_GENERATING.value}),
            success_stage=RunStage.FOO_REVIEW.value,
        )

        async def execute(ctx: TaskContext) -> TaskResult:
            # Your task-specific logic here
            result = await provider.generate(...)
            await save_result(...)
            return TaskResult(status="success", extra={"my_field": value})

        return run_task(self, run_id, config, execute)
"""

# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from celery.exceptions import Ignore, SoftTimeLimitExceeded
from creator_domain.models.stage import RunStage
from creator_provider.exceptions import ProviderTimeoutError, RateLimitError
from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
from creator_service.run_service import run_service as _run_service
from creator_service.task_tracking_service import task_tracking_service as _task_tracking_service
from creator_service.usage_service import resolve_workspace_id_from_run

redis: Any
try:
    import redis
except ImportError:
    redis = None

logger = logging.getLogger(__name__)


@dataclass
class TaskRunnerConfig:
    """Configuration for a task runner invocation."""

    task_name: str
    allowed_stages: frozenset[RunStage]
    safe_stages: frozenset[str]
    success_stage: str | None = None
    safe_failure_stages: frozenset[str] | None = None  # defaults to safe_stages
    skip_stage_guard: bool = False
    raise_on_stage_guard: bool = True
    no_fail_transition_exceptions: tuple[type[Exception], ...] = (ValueError,)


@dataclass
class TaskContext:
    """Context passed to the task execution function."""

    run_id: int
    task_id: str
    run: dict[str, Any]
    workspace_id: int | None
    project_id: int | None
    start_time: datetime


@dataclass
class TaskResult:
    """Result returned by the task execution function."""

    status: str = "success"
    extra: dict[str, object] = field(default_factory=dict)


class StageGuardError(ValueError):
    """Run is not in an acceptable stage. Do NOT mutate run to FAILED."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_redis_client() -> Any | None:
    if redis is None:
        return None
    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


async def _run_task_inner(
    run_id: int,
    task_id: str,
    config: TaskRunnerConfig,
    execute: Callable[[TaskContext], Awaitable[TaskResult]],
) -> dict[str, object]:
    """Inner async execution with full lifecycle management."""
    start_time = datetime.now(timezone.utc)

    try:
        # 1. Task tracking: start
        try:
            await _task_tracking_service.record_task_start(run_id, config.task_name, task_id)
            await _task_tracking_service.mark_running(task_id)
        except Exception:
            logger.warning("Failed to record task start", exc_info=True)

        # 2. Stage guard
        run = await _run_service.storage.get_run(run_id)
        if run is None and not config.skip_stage_guard:
            raise StageGuardError(f"Run {run_id} not found")

        if run is not None and not config.skip_stage_guard:
            try:
                current = RunStage(run["current_stage"])
            except ValueError as exc:
                raise StageGuardError(
                    f"Run {run_id} has invalid stage {run['current_stage']!r}"
                ) from exc

            if current not in config.allowed_stages:
                raise StageGuardError(
                    f"Run {run_id} is in stage {current.value}, "
                    f"expected one of {', '.join(s.value for s in config.allowed_stages)}"
                )
            if run.get("status") == "cancelled":
                raise StageGuardError(f"Run {run_id} is cancelled")

        # 3. Resolve workspace/project context
        workspace_id: int | None = None
        project_id: int | None = None
        if run is not None:
            workspace_id = await resolve_workspace_id_from_run(run_id)
            project_id = run.get("project_id")

        # 4. Execute task-specific logic
        ctx = TaskContext(
            run_id=run_id,
            task_id=task_id,
            run=run or {},
            workspace_id=workspace_id,
            project_id=project_id,
            start_time=start_time,
        )

        result = await execute(ctx)

        # 5. Stage transition based on result status
        if config.success_stage is not None:
            safe_failure_stages = config.safe_failure_stages or config.safe_stages
            if result.status == "success":
                applied, _ = await _run_service.storage.conditional_update_run(
                    run_id,
                    {"current_stage": config.success_stage, "status": "running"},
                    expected_stages=config.safe_stages,
                )
                if not applied:
                    logger.info(
                        "Run %d stage changed during %s -- skipping success transition",
                        run_id,
                        config.task_name,
                    )
            else:
                applied, _ = await _run_service.storage.conditional_update_run(
                    run_id,
                    {"current_stage": RunStage.FAILED.value, "status": "failed"},
                    expected_stages=safe_failure_stages,
                )
                if not applied:
                    logger.info(
                        "Run %d stage changed during %s -- skipping FAILED transition",
                        run_id,
                        config.task_name,
                    )

        # 6. Mark success/failure based on result status
        end_time = datetime.now(timezone.utc)
        try:
            if result.status == "success":
                await _task_tracking_service.mark_success(task_id)
            else:
                await _task_tracking_service.mark_failed(
                    task_id, "task_result", f"status={result.status}"
                )
        except Exception:
            logger.warning("Failed to record task outcome", exc_info=True)

        return {
            "task_id": task_id,
            "run_id": run_id,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": (end_time - start_time).total_seconds(),
            "status": result.status,
            **result.extra,
        }
    finally:
        pass


async def _handle_general_failure(
    task_id: str,
    run_id: int,
    config_task_name: str,
    safe_failure_stages: frozenset[str],
    exc: Exception,
) -> None:
    """Consolidate error-handler async work into a single coroutine."""
    try:
        await _task_tracking_service.mark_failed(task_id, type(exc).__name__, str(exc)[:500])
    except Exception:
        logger.warning("Failed to record task failure", exc_info=True)
    try:
        applied, _ = await _run_service.storage.conditional_update_run(
            run_id,
            {"current_stage": RunStage.FAILED.value, "status": "failed"},
            expected_stages=safe_failure_stages,
        )
        if not applied:
            logger.info(
                "Run %d stage changed during %s -- skipping FAILED transition",
                run_id,
                config_task_name,
            )
    except Exception:
        logger.exception("Failed to mark run %d as FAILED after task error", run_id)


def run_task(
    celery_self: Any,
    run_id: int,
    config: TaskRunnerConfig,
    execute: Callable[[TaskContext], Awaitable[TaskResult]],
) -> dict[str, object]:
    """Synchronous entry point for Celery tasks. Handles all error cases.

    This wraps asyncio.run() and provides consistent error handling:
    - StageGuardError → mark_rejected, re-raise (no FAILED transition)
    - SoftTimeLimitExceeded → FAILED transition, re-raise
    - Retryable errors → re-raise for Celery retry
    - Other errors → mark_failed + FAILED transition, re-raise
    """
    task_id = str(getattr(getattr(celery_self, "request", None), "id", None) or f"run-{run_id}")
    safe_failure_stages = config.safe_failure_stages or config.safe_stages

    try:
        return asyncio.run(_run_task_inner(run_id, task_id, config, execute))
    except StageGuardError:
        try:
            asyncio.run(_task_tracking_service.mark_rejected(task_id, "stage_guard"))
        except Exception:
            logger.warning("Failed to record task rejection", exc_info=True)
        if config.raise_on_stage_guard:
            raise
        raise Ignore()
    except SoftTimeLimitExceeded:
        logger.error("Task %s timed out for run %s", config.task_name, run_id)
        try:
            asyncio.run(
                _run_service.storage.conditional_update_run(
                    run_id,
                    {"current_stage": RunStage.FAILED.value, "status": "failed"},
                    expected_stages=safe_failure_stages,
                )
            )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after timeout", run_id)
        raise
    except Exception as exc:
        if isinstance(exc, config.no_fail_transition_exceptions):
            raise
        if (
            isinstance(exc, (ProviderTimeoutError, RateLimitError))
            and celery_self.request.retries < celery_self.max_retries
        ):
            raise
        try:
            asyncio.run(
                _handle_general_failure(task_id, run_id, config.task_name, safe_failure_stages, exc)
            )
        except Exception:
            logger.exception("Failed error cleanup for run %d", run_id)
        raise


# --- GPU Lock helpers for use in execute() callbacks ---


@dataclass
class GpuLockContext:
    """Manages GPU lock acquisition/release within a task."""

    task_id: str
    redis_client: Any | None = None
    acquired: bool = False
    acquired_at: str | None = None
    released_at: str | None = None

    def acquire(self, lock_id: str | None = None) -> None:
        """Acquire GPU lock. Raises RuntimeError if Redis unavailable."""
        self.redis_client = _get_redis_client()
        if self.redis_client is None:
            raise RuntimeError("Redis client is unavailable; cannot acquire GPU lock")
        acquire_gpu_lock(self.redis_client, lock_id or self.task_id)
        self.acquired = True
        self.acquired_at = _utc_now_iso()

    def release(self, lock_id: str | None = None) -> None:
        """Release GPU lock if acquired."""
        if not self.acquired:
            return
        try:
            release_gpu_lock(self.redis_client, lock_id or self.task_id)
            self.released_at = _utc_now_iso()
        except Exception:
            logger.exception("Failed to release GPU lock for %s", lock_id or self.task_id)
        finally:
            self.acquired = False
