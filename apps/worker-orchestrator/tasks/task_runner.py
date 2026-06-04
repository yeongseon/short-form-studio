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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from celery.exceptions import Ignore, SoftTimeLimitExceeded
from creator_domain.models.stage import REVIEW_STAGES, RunStage
from creator_provider.exceptions import ProviderTimeoutError, RateLimitError
from creator_provider.gpu_lock import (
    GPU_LOCK_TIMEOUT_SECONDS,
    acquire_gpu_lock,
    release_gpu_lock,
    renew_gpu_lock,
)
from creator_provider.versioned_assets import clear_loaded_asset_versions, get_loaded_asset_versions
from creator_service.run_service import run_service as _run_service
from creator_service.task_tracking_service import task_tracking_service as _task_tracking_service
from creator_service.usage_service import resolve_workspace_id_from_run


redis: Any
try:
    import redis
except ImportError:
    redis = None


def run_in_worker_loop(coro):
    """Lazy-import wrapper to avoid import errors in non-worker contexts (e.g. API)."""
    from worker_loop import run_in_worker_loop as _run
    return _run(coro)


logger = logging.getLogger(__name__)

# Statuses that must never be overwritten by worker completion transitions.
_TERMINAL_STATUSES = frozenset({"cancelled"})


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


def validate_artifact_path(path: str, artifact_root: str) -> str:
    resolved = os.path.realpath(path)
    root = os.path.realpath(artifact_root)
    if not resolved.startswith(root + os.sep) and resolved != root:
        raise ValueError(f"Path {path!r} is outside artifact root")
    return resolved


async def _run_task_inner(
    run_id: int,
    task_id: str,
    config: TaskRunnerConfig,
    execute: Callable[[TaskContext], Awaitable[TaskResult]],
) -> dict[str, object]:
    """Inner async execution with full lifecycle management."""
    # Reject new work if graceful shutdown is in progress
    from celery_app import is_shutting_down

    if is_shutting_down():
        logger.info("Rejecting task %s: graceful shutdown in progress", task_id)
        raise Ignore()
    # Reset asset version tracking to isolate from import-time loads
    clear_loaded_asset_versions()
    start_time = datetime.now(timezone.utc)

    try:
        existing_task = await _task_tracking_service.storage.get_by_celery_id(task_id)
        if (
            existing_task is not None
            and not task_id.startswith("run-")
            and existing_task.get("status") == "success"
            and existing_task.get("run_id") == run_id
            and existing_task.get("task_type") == config.task_name
        ):
            logger.info("Task %s already succeeded (idempotency guard), skipping", task_id)
            end_time = datetime.now(timezone.utc)
            return {
                "task_id": task_id,
                "run_id": run_id,
                "status": "success",
                "idempotent_skip": True,
                "asset_versions": {},
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": 0.0,
            }
    except Exception:
        logger.warning("Failed idempotency guard lookup", exc_info=True)

    # 1. Task tracking: exclusive claim (only one worker executes per task)
    try:
        start_result = await _task_tracking_service.record_task_start(
            run_id, config.task_name, task_id
        )
        if not task_id.startswith("run-"):
            if start_result is None:
                logger.info("Task %s already claimed by another worker, skipping", task_id)
                end_time = datetime.now(timezone.utc)
                return {
                    "task_id": task_id,
                    "run_id": run_id,
                    "status": "success",
                    "idempotent_skip": True,
                    "asset_versions": {},
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "duration_seconds": 0.0,
                }
            if start_result.status == "success":
                logger.info("Task %s already succeeded (atomic start guard), skipping", task_id)
                end_time = datetime.now(timezone.utc)
                return {
                    "task_id": task_id,
                    "run_id": run_id,
                    "status": "success",
                    "idempotent_skip": True,
                    "asset_versions": {},
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "duration_seconds": 0.0,
                }
    except Exception:
        if not task_id.startswith("run-"):
            logger.error("Failed to record task start — refusing to execute without claim", exc_info=True)
            raise
        logger.warning("Failed to record task start (synthetic task ID, continuing)", exc_info=True)

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
    logger.info(
        "Task context resolved",
        extra={
            "task_name": config.task_name,
            "run_id": run_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
        },
    )

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
            # Use "paused" for review stages to indicate awaiting human action
            target_status = "paused" if config.success_stage in {s.value for s in REVIEW_STAGES} else "running"
            applied, _ = await _run_service.storage.conditional_update_run(
                run_id,
                {"current_stage": config.success_stage, "status": target_status},
                expected_stages=config.safe_stages,
                rejected_statuses=_TERMINAL_STATUSES,
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
                rejected_statuses=_TERMINAL_STATUSES,
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
        "asset_versions": get_loaded_asset_versions(),
    }


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
            rejected_statuses=_TERMINAL_STATUSES,
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

    This wraps run_in_worker_loop() and provides consistent error handling:
    - StageGuardError → mark_rejected, re-raise (no FAILED transition)
    - SoftTimeLimitExceeded → FAILED transition, re-raise
    - Retryable errors → re-raise for Celery retry
    - Other errors → mark_failed + FAILED transition, re-raise
    """
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
    validated_message = validate_task_message(message)
    validated_run_id = validated_message["run_id"]

    task_id = str(getattr(request, "id", None) or f"run-{validated_run_id}")
    safe_failure_stages = config.safe_failure_stages or config.safe_stages

    try:
        return run_in_worker_loop(_run_task_inner(validated_run_id, task_id, config, execute))
    except StageGuardError:
        try:
            run_in_worker_loop(_task_tracking_service.mark_rejected(task_id, "stage_guard"))
        except Exception:
            logger.warning("Failed to record task rejection", exc_info=True)
        if config.raise_on_stage_guard:
            raise
        raise Ignore()
    except SoftTimeLimitExceeded:
        logger.error("Task %s timed out for run %s", config.task_name, validated_run_id)
        try:
            run_in_worker_loop(
                _run_service.storage.conditional_update_run(
                    validated_run_id,
                    {"current_stage": RunStage.FAILED.value, "status": "failed"},
                    expected_stages=safe_failure_stages,
                    rejected_statuses=_TERMINAL_STATUSES,
                )
            )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after timeout", validated_run_id)
        raise
    except Ignore:
        raise
    except Exception as exc:
        if isinstance(exc, config.no_fail_transition_exceptions):
            try:
                run_in_worker_loop(
                    _task_tracking_service.mark_failed(task_id, type(exc).__name__, str(exc)[:500])
                )
            except Exception:
                logger.warning("Failed to record task failure", exc_info=True)
            raise
        if (
            isinstance(exc, (ProviderTimeoutError, RateLimitError))
            and celery_self.request.retries < celery_self.max_retries
        ):
            raise
        try:
            run_in_worker_loop(
                _handle_general_failure(
                    task_id,
                    validated_run_id,
                    config.task_name,
                    safe_failure_stages,
                    exc,
                )
            )
        except Exception:
            logger.exception("Failed error cleanup for run %d", validated_run_id)
        raise


# --- GPU Lock helpers for use in execute() callbacks ---


@dataclass
class GpuLockContext:
    """Manages GPU lock acquisition/release within a task."""

    task_id: str
    redis_client: Any | None = None
    acquired: bool = False
    lock_lost: bool = False
    _token: str | None = None
    acquired_at: str | None = None
    released_at: str | None = None
    _renewal_task: Any | None = None

    def acquire(self, lock_id: str | None = None) -> None:
        """Acquire GPU lock and start auto-renewal. Raises RuntimeError if Redis unavailable."""
        self.redis_client = _get_redis_client()
        if self.redis_client is None:
            raise RuntimeError("Redis client is unavailable; cannot acquire GPU lock")
        self._token = acquire_gpu_lock(self.redis_client, lock_id or self.task_id)
        self.acquired = True
        self.lock_lost = False
        self.acquired_at = _utc_now_iso()
        self.start_auto_renewal()

    def renew(self, timeout: int = GPU_LOCK_TIMEOUT_SECONDS) -> bool:
        """Renew GPU lock lease. Returns True if renewed, False if lock lost."""
        if not self.acquired or self._token is None or self.redis_client is None:
            return False
        return renew_gpu_lock(self.redis_client, self._token, timeout=timeout)

    def start_auto_renewal(self, timeout: int = GPU_LOCK_TIMEOUT_SECONDS) -> None:
        """Start background task to auto-renew the GPU lease at half the timeout interval."""
        if not self.acquired or self._renewal_task is not None:
            return

        interval = max(timeout // 2, 1)

        async def _renew_loop() -> None:
            while self.acquired:
                await asyncio.sleep(interval)
                if not self.acquired:
                    break
                try:
                    ok = self.renew(timeout=timeout)
                    if not ok:
                        self.lock_lost = True
                        self.acquired = False
                        logger.warning("GPU lease renewal failed for %s (lock lost)", self.task_id)
                        break
                except Exception:
                    self.lock_lost = True
                    self.acquired = False
                    logger.warning("GPU lease renewal error for %s", self.task_id, exc_info=True)
                    break

        self._renewal_task = asyncio.create_task(_renew_loop())

    def stop_auto_renewal(self) -> None:
        """Cancel the auto-renewal background task."""
        if self._renewal_task is not None:
            self._renewal_task.cancel()
            self._renewal_task = None

    def release(self, lock_id: str | None = None) -> None:
        """Release GPU lock if acquired. Raises RuntimeError if lock was lost."""
        self.stop_auto_renewal()
        was_lost = self.lock_lost
        if self.acquired and self._token is not None:
            try:
                released = release_gpu_lock(self.redis_client, self._token)
                if released:
                    self.released_at = _utc_now_iso()
                else:
                    logger.warning(
                        "GPU lock release returned False for %s (lock expired or stolen)",
                        lock_id or self.task_id,
                    )
                    was_lost = True
            except Exception:
                logger.exception("Failed to release GPU lock for %s", lock_id or self.task_id)
            finally:
                self.acquired = False
                self._token = None
        if was_lost:
            raise RuntimeError(f"GPU lock was lost during execution for {lock_id or self.task_id}")


def validate_task_message(message: dict[str, Any]) -> dict[str, Any]:
    if "run_id" not in message:
        raise ValueError("missing required field: run_id")
    run_id = message["run_id"]
    if isinstance(run_id, bool) or not isinstance(run_id, int):
        raise ValueError("run_id must be int")
    if run_id <= 0:
        raise ValueError("run_id must be positive")

    if "task_name" in message and not isinstance(message["task_name"], str):
        raise ValueError("task_name must be str")
    if "args" in message and not isinstance(message["args"], list):
        raise ValueError("args must be list")
    if "kwargs" in message and not isinstance(message["kwargs"], dict):
        raise ValueError("kwargs must be dict")
    validated = {k: message[k] for k in ("run_id", "task_name", "args", "kwargs") if k in message}

    # Semantic validation of kwargs
    kwargs = validated.get("kwargs", {})
    if "model_key" in kwargs:
        validate_model_key(kwargs["model_key"])
    for key, value in kwargs.items():
        validate_string_arg(value, key)

    return validated


_MAX_STRING_ARG_LENGTH = 4096

_ALLOWED_MODEL_KEYS: frozenset[str] = frozenset(
    os.getenv(
        "ALLOWED_MODEL_KEYS",
        "qwen3:4b,gpt-4o-mini,claude-sonnet,gemini-2.0-flash,"
        "llama-3.3-70b-versatile,"
        "sd-1.5,dall-e-3,sd3-medium,imagen-3,pollinations,placeholder,"
        "eleven_multilingual_v2,tts-1,whisper-small,tts-1-hd,edge-tts,"
        "groq-whisper-large-v3-turbo"
    ).split(",")
)


def validate_model_key(key: str) -> None:
    """Validate model_key against the allowed whitelist."""
    if not isinstance(key, str) or not key.strip():
        raise ValueError("model_key must be a non-empty string")
    if key not in _ALLOWED_MODEL_KEYS:
        raise ValueError(f"model_key {key!r} is not in the allowed list")


def validate_string_arg(value: Any, name: str) -> None:
    """Validate that a string argument doesn't exceed max length."""
    if isinstance(value, str) and len(value) > _MAX_STRING_ARG_LENGTH:
        raise ValueError(f"{name} exceeds maximum length of {_MAX_STRING_ARG_LENGTH}")
