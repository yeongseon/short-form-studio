"""Celery task for script generation via model providers."""

# ruff: noqa: E402
# pyright: reportMissingImports=false

from __future__ import annotations

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

from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
from creator_provider.registry import ProviderRegistry
from creator_service.run_service import run_service as _run_service
from creator_service.script_service import script_service as _script_service
from creator_service.task_tracking_service import task_tracking_service as _task_tracking_service

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


@celery_app.task(bind=True, name="generate_script")
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
                generated = await provider.generate(prompt, params)
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
        raise
    except Exception as exc:
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
