"""Celery task for script generation via model providers.

Idempotency:
    IDEMPOTENT - Safe to retry. Task uses stage guards to reject stale invocations:
    - Before writing any side effects (save_draft, stage transition), it checks that the run
      is still in an acceptable stage (IDEA_READY or SCRIPT_GENERATING).
    - If the run has advanced to SCRIPT_REVIEW or later, the task detects this and raises
      _StageGuardError without mutating the run state. This allows duplicate tasks from
      crashed workers to safely no-op.
    - Multiple invocations with the same (run_id, idea_brief, model_key) will each attempt
      generation, but only the first successful invocation's stage transition will stick
      (conditional_update_run uses compare-and-set).
    - Idempotency is guaranteed by acks_late + task_reject_on_worker_lost:
      If a worker crashes mid-execution, the task message is redelivered.

Side effects:
    - Database: Saves script draft (run_id, source_type='generated_by_model', markdown_content).
    - Database: Atomically transitions run stage to SCRIPT_REVIEW (via conditional_update_run).
    - GPU Resource: Acquires/releases GPU lock in Redis (if provider requires GPU).
    - No file creation: Results are stored in database, not filesystem.

Retry safety:
    SAFE FOR RETRY - Configured with:
    - max_retries=3
    - autoretry_for=(ProviderTimeoutError, RateLimitError)
    - retry_backoff=True, retry_jitter=True (exponential backoff with jitter)
    - soft_time_limit=300s, hard time_limit=360s
    Transient failures (timeouts, rate limits) are retried; permanent failures (ProviderError)
    are raised immediately and sent to DLQ.
    On timeout (soft_time_limit exceeded): Task transitions run to FAILED atomically
    before raising, ensuring the run doesn't stay stuck in SCRIPT_GENERATING.
"""

# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

# pyright: reportMissingImports=false
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

redis: Any  # optional dependency; may be None at runtime
try:
    import redis
except ImportError:
    redis = None

from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
from creator_provider.registry import ProviderRegistry
from creator_service.cost_config import COST_SCRIPT_GENERATION
from creator_service.run_service import run_service as _run_service
from creator_service.script_service import script_service as _script_service
from creator_service.task_tracking_service import task_tracking_service as _task_tracking_service
from creator_service.telemetry import trace_task
from creator_service.usage_service import record_provider_call, resolve_workspace_id_from_run

logger = logging.getLogger(__name__)

_ALLOWED_STAGES = frozenset({RunStage.IDEA_READY, RunStage.SCRIPT_GENERATING})

# Stages where writing SCRIPT_REVIEW or FAILED is safe — the run hasn't
# advanced past generation. The task may start directly from IDEA_READY
# or from SCRIPT_GENERATING after the API-side CAS.
_SAFE_STAGES = frozenset(
    {
        RunStage.IDEA_READY.value,
        RunStage.SCRIPT_GENERATING.value,
    }
)


class _StageGuardError(ValueError):
    """Raised when a run is not in an acceptable stage for generation.

    This is a validation/rejection error — the run state must NOT be mutated
    to FAILED because the run may already be in a later stage (e.g. SCRIPT_REVIEW).
    """


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_prompt(idea_brief: str, instructions: str | None) -> str:
    idea = idea_brief.strip()
    if not instructions:
        return idea

    extra = instructions.strip()
    if not extra:
        return idea

    return f"{idea}\n\nAdditional instructions:\n{extra}"


def _get_redis_client() -> Any | None:
    if redis is None:
        return None
    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


async def _remove_active_task_id_best_effort(run_id: int, task_id: str) -> None:
    remover: Any = getattr(_run_service.storage, "remove_active_task_id", None)
    if not callable(remover):
        return
    try:
        maybe_result = remover(run_id, task_id)
        if asyncio.iscoroutine(maybe_result):
            await maybe_result
    except Exception:
        logger.exception("Failed to remove active task id %s for run %d", task_id, run_id)


@celery_app.task(
    bind=True,
    autoretry_for=(ProviderTimeoutError, RateLimitError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=300,
    time_limit=360,
    name="generate_script",
)
@trace_task("generate_script")
def generate_script(
    self,
    run_id: int,
    idea_brief: str,
    model_key: str = "qwen3-4b",
    instructions: str | None = None,
) -> dict[str, object]:
    start_time = datetime.now(timezone.utc)
    start_iso = start_time.isoformat()
    task_id = str(getattr(getattr(self, "request", None), "id", None) or f"run-{run_id}")
    # Idempotency: acks_late + task_reject_on_worker_lost ensures redelivery on crash.
    # If the run has already advanced past this stage, the worker's stage check will
    # naturally skip processing (handled by run_service stage validation).
    prompt = _build_prompt(idea_brief, instructions)

    provider_type: str | None = None
    endpoint: str | None = None
    gpu_lock_acquired_at: str | None = None
    gpu_lock_released_at: str | None = None
    redis_client: Any | None = None
    lock_acquired = False

    async def _run_task() -> dict[str, object]:
        nonlocal provider_type, endpoint, gpu_lock_acquired_at, gpu_lock_released_at
        nonlocal redis_client, lock_acquired
        try:
            try:
                await _task_tracking_service.record_task_start(run_id, "generate_script", task_id)
                await _task_tracking_service.mark_running(task_id)
            except Exception:
                logger.warning("Failed to record task start", exc_info=True)
            # 1. Stage guard — reject before any side effects.
            run = await _run_service.storage.get_run(run_id)
            if run is None:
                raise _StageGuardError(f"Run {run_id} not found")

            try:
                current = RunStage(run["current_stage"])
            except ValueError as exc:
                raise _StageGuardError(
                    f"Run {run_id} has invalid stage {run['current_stage']!r}"
                ) from exc
            if current not in _ALLOWED_STAGES:
                raise _StageGuardError(
                    f"Run {run_id} is in stage {current.value}, "
                    f"expected one of {', '.join(s.value for s in _ALLOWED_STAGES)}"
                )
            if run.get("status") == "cancelled":
                raise _StageGuardError(f"Run {run_id} is cancelled")
            workspace_id = await resolve_workspace_id_from_run(run_id)
            project_id = run.get("project_id")

            # 2. Provider resolution (sync — blocks briefly, fine in Celery worker).
            registry = ProviderRegistry.create_default()
            entry = registry.resolve(model_key)
            provider = registry.get_provider(model_key)

            provider_type = entry.provider_type
            endpoint = entry.endpoint

            # 3. GPU lock acquisition (sync).
            if entry.requires_gpu:
                redis_client = _get_redis_client()
                if redis_client is None:
                    raise RuntimeError("Redis client is unavailable; cannot acquire GPU lock")
                acquire_gpu_lock(redis_client, task_id)
                lock_acquired = True
                gpu_lock_acquired_at = _utc_now_iso()

            try:
                # 4. Generation, save, advance stage.
                params = dict(entry.default_params or {})
                try:
                    generated = await provider.generate(prompt, params)
                except (TimeoutError, ConnectionError) as exc:
                    raise ProviderTimeoutError(
                        f"Provider timed out during script generation for run {run_id}"
                    ) from exc
                except SoftTimeLimitExceeded:
                    raise
                except Exception as exc:
                    message = str(exc).lower()
                    if "429" in message or "rate" in message:
                        raise RateLimitError(
                            f"Provider rate limited script generation for run {run_id}"
                        ) from exc
                    raise ProviderError(
                        f"Provider failed script generation for run {run_id}"
                    ) from exc
                try:
                    await record_provider_call(
                        run_id,
                        entry.provider_type,
                        model_key,
                        "llm",
                        cost_usd=COST_SCRIPT_GENERATION,
                        workspace_id=workspace_id,
                        project_id=project_id,
                    )
                except Exception:
                    logger.warning("Failed to record provider usage", exc_info=True)
                await _script_service.save_draft(
                    run_id=run_id,
                    source_type="generated_by_model",
                    markdown_content=generated,
                )
                # Atomic success transition: only advance if run is still in a
                # generating-compatible stage. Uses compare-and-set at the storage
                # layer — no TOCTOU gap.
                applied, _ = await _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.SCRIPT_REVIEW.value,
                        "status": "running",
                    },
                    expected_stages=_SAFE_STAGES,
                )
                if not applied:
                    logger.info(
                        "Run %d stage changed during generation -- skipping SCRIPT_REVIEW transition",
                        run_id,
                    )
            finally:
                if lock_acquired:
                    try:
                        release_gpu_lock(redis_client, task_id)
                        gpu_lock_released_at = _utc_now_iso()
                    except Exception:
                        logger.exception("Failed to release GPU lock for task %s", task_id)

            end_time = datetime.now(timezone.utc)
            duration_seconds = (end_time - start_time).total_seconds()
            try:
                await _task_tracking_service.mark_success(task_id)
            except Exception:
                logger.warning("Failed to record task success", exc_info=True)
            return {
                "task_id": task_id,
                "run_id": run_id,
                "model_key": model_key,
                "provider_type": provider_type,
                "endpoint": endpoint,
                "gpu_lock_acquired_at": gpu_lock_acquired_at,
                "gpu_lock_released_at": gpu_lock_released_at,
                "prompt_summary": idea_brief[:200],
                "start_time": start_iso,
                "end_time": end_time.isoformat(),
                "duration_seconds": duration_seconds,
                "status": "success",
                "error": None,
            }
        finally:
            await _remove_active_task_id_best_effort(run_id, task_id)

    try:
        return asyncio.run(_run_task())
    except _StageGuardError:
        # Validation rejection — do NOT mutate run state to FAILED.
        # A stale/duplicate task should not downgrade a run already past generation.
        try:
            asyncio.run(_task_tracking_service.mark_rejected(task_id, "stage_guard"))
        except Exception:
            logger.warning("Failed to record task rejection", exc_info=True)
        raise
    except SoftTimeLimitExceeded:
        logger.error("Task timed out for run %s", run_id)
        # Transition run to FAILED so it doesn't stay stuck in generating stage
        try:
            asyncio.run(
                _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.FAILED.value,
                        "status": "failed",
                    },
                    expected_stages=_SAFE_STAGES,
                )
            )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after timeout", run_id)
        raise
    except Exception as exc:
        if (
            isinstance(exc, ProviderTimeoutError | RateLimitError)
            and self.request.retries < self.max_retries
        ):
            raise
        try:
            asyncio.run(
                _task_tracking_service.mark_failed(task_id, type(exc).__name__, str(exc)[:500])
            )
        except Exception:
            logger.warning("Failed to record task failure", exc_info=True)
        # Atomic conditional fail: only mark FAILED if run is still in a
        # generating-compatible stage. Uses compare-and-set — no TOCTOU gap.
        try:
            applied, _ = asyncio.run(
                _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.FAILED.value,
                        "status": "failed",
                    },
                    expected_stages=_SAFE_STAGES,
                )
            )
            if not applied:
                logger.info(
                    "Run %d stage changed during generation -- skipping FAILED transition",
                    run_id,
                )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after task error", run_id)

        raise
