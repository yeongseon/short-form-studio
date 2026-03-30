# pyright: reportMissingImports=false
"""Celery task for script generation via model providers."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../..", "packages"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../..", "packages", "creator-service"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../..", "packages", "creator-provider"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../..", "packages", "creator-domain"))

try:
    import redis
except ImportError:
    redis = None  # type: ignore[assignment]

from celery_app import celery_app

try:
    from creator_domain.models.stage import RunStage
except ImportError:
    from models.stage import RunStage

try:
    from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
    from creator_provider.registry import ProviderRegistry
except ImportError:
    from gpu_lock import acquire_gpu_lock, release_gpu_lock
    from registry import ProviderRegistry

try:
    from creator_service.run_service import run_service as _run_service
except ImportError:
    from run_service import run_service as _run_service

try:
    from creator_service.script_service import script_service as _script_service
except ImportError:
    from script_service import script_service as _script_service

logger = logging.getLogger(__name__)

_ALLOWED_STAGES = frozenset({RunStage.IDEA_READY, RunStage.SCRIPT_GENERATING})


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

    async def _check_stage_guard() -> None:
        """Validate run stage BEFORE any provider/GPU setup."""
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

    async def _run_generation() -> str:
        """Execute generation, save draft, advance stage."""
        params = dict(entry.default_params or {})
        generated = await provider.generate(prompt, params)
        await _script_service.save_draft(
            run_id=run_id,
            source_type="generated_by_model",
            markdown_content=generated,
        )
        await _run_service.storage.update_run(
            run_id,
            {
                "current_stage": RunStage.SCRIPT_REVIEW.value,
                "status": "running",
            },
        )
        return generated

    try:
        # Stage guard FIRST — before any provider resolution or GPU lock.
        # If the run is not in an allowed stage, reject immediately.
        asyncio.run(_check_stage_guard())

        registry = ProviderRegistry.create_default()
        entry = registry.resolve(model_key)
        provider = registry.get_provider(model_key)

        provider_type = entry.provider_type
        endpoint = entry.endpoint

        if entry.requires_gpu:
            redis_client = _get_redis_client()
            if redis_client is None:
                raise RuntimeError("Redis client is unavailable; cannot acquire GPU lock")
            acquire_gpu_lock(redis_client, task_id)
            lock_acquired = True
            gpu_lock_acquired_at = _utc_now_iso()

        try:
            asyncio.run(_run_generation())
        finally:
            if lock_acquired:
                try:
                    release_gpu_lock(redis_client, task_id)
                    gpu_lock_released_at = _utc_now_iso()
                except Exception:
                    logger.exception("Failed to release GPU lock for task %s", task_id)

        end_time = datetime.now(timezone.utc)
        duration_seconds = (end_time - start_time).total_seconds()
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
    except _StageGuardError:
        # Validation rejection — do NOT mutate run state to FAILED.
        # A stale/duplicate task should not downgrade a run already past generation.
        raise

    except Exception:
        try:
            asyncio.run(
                _run_service.storage.update_run(
                    run_id,
                    {
                        "current_stage": RunStage.FAILED.value,
                        "status": "failed",
                    },
                )
            )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after task error", run_id)

        raise
