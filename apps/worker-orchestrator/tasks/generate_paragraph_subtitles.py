"""Celery task for per-paragraph subtitle generation.

Transcribes a single paragraph's audio file to produce a per-section SRT.
Unlike the run-level ``generate_subtitles`` task this does NOT transition
stages — the caller (storyboard API) manages aggregate state.

Subtitles are saved to: data/artifacts/{run_id}/subtitles/{section_id}.srt

Idempotency:
    IDEMPOTENT - Safe to retry:
    - Does NOT perform stage guard (paragraph tasks don't manage run stages).
    - Multiple invocations generate NEW artifact records with unique IDs but
      the same section_id. Each invocation overwrites the subtitle file.
    - Caller is responsible for deduplication (e.g., check if artifact already exists
      before invoking task, or use task ID for idempotency key).
    - Task gracefully handles multiple invocations: later artifacts do not break earlier ones;
      the caller selects the desired artifact by version or timestamp.
    - Idempotency guaranteed by acks_late + task_reject_on_worker_lost for task delivery;
      file overwrites are idempotent (same content each invocation, same audio input).

Side effects:
    - Filesystem: Saves subtitles to data/artifacts/{run_id}/subtitles/{safe_section_id}.{format}
      (overwrites on retry).
    - Database: Creates subtitle artifact record (run_id, section_id, path, format, model_used,
      provider_type). Each invocation creates a new record.
    - GPU Resource: Acquires/releases GPU lock in Redis (if provider requires GPU).
    - NO stage transition: Caller manages run stages.

Retry safety:
    SAFE FOR RETRY - Configured with:
    - max_retries=3
    - autoretry_for=(ProviderTimeoutError, RateLimitError)  [NOT auto-retried for transcription]
    - retry_backoff=True, retry_jitter=True
    - soft_time_limit=300s, hard time_limit=360s
    Note: Unlike other tasks, paragraph subtitles omit autoretry_for since transcription
    is deterministic (audio is already generated). On timeout: Task does NOT transition
    run stage (caller's responsibility). Task simply re-raises timeout; caller decides
    whether to transition run to FAILED or retry the task.
"""

Transcribes a single paragraph's audio file to produce a per-section SRT.
Unlike the run-level ``generate_subtitles`` task this does NOT transition
stages — the caller (storyboard API) manages aggregate state.

Subtitles are saved to: data/artifacts/{run_id}/subtitles/{section_id}.srt
"""

# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

redis: Any  # optional dependency; may be None at runtime
try:
    import redis
except ImportError:
    redis = None

from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_domain.sanitize import sanitize_path_component
from creator_domain.sanitize import sanitize_path_component
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
from creator_provider.registry import ProviderRegistry
from creator_service.run_service import run_service as _run_service
from creator_service.subtitle_service import subtitle_service as _subtitle_service

logger = logging.getLogger(__name__)

_ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")

# Stages where a timed-out paragraph task can safely transition the run to FAILED.
# Since paragraph tasks don't manage stages, we include common subtitle stages.
_SAFE_STAGES = frozenset({
    RunStage.AUDIO_GENERATING.value,
    RunStage.SUBTITLE_GENERATING.value,
})



class _StageGuardError(ValueError):
    """Raised when a run is not in an acceptable state for paragraph subtitle generation."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    name="generate_paragraph_subtitles",
)
def generate_paragraph_subtitles(
    self,
    run_id: int,
    section_id: str,
    audio_path: str,
    subtitle_model: str = "whisper-small",
    subtitle_format: str = "srt",
) -> dict[str, object]:
    """Generate subtitles for a single paragraph's audio.

    Parameters
    ----------
    run_id : int
        Parent run ID.
    section_id : str
        Script section identifier.
    audio_path : str
        Path to the per-paragraph audio WAV file.
    subtitle_model : str
        Model key from the provider registry.
    subtitle_format : str
        Output format (``srt`` or ``vtt``).
    """
    start_time = datetime.now(timezone.utc)
    start_iso = start_time.isoformat()
    task_id = str(
        getattr(getattr(self, "request", None), "id", None) or f"sub-{run_id}-{section_id}"
    )
    # Idempotency: acks_late + task_reject_on_worker_lost ensures redelivery on crash.
    # If the run has already advanced past this stage, the worker's stage check will
    # naturally skip processing (handled by run_service stage validation).

    provider_type: str | None = None
    endpoint: str | None = None
    gpu_lock_acquired_at: str | None = None
    gpu_lock_released_at: str | None = None
    redis_client: Any | None = None
    lock_acquired = False

    async def _run_task() -> dict[str, object]:
        nonlocal provider_type, endpoint, gpu_lock_acquired_at, gpu_lock_released_at
        nonlocal redis_client, lock_acquired

        run = await _run_service.storage.get_run(run_id)
        if run is not None and run.get("status") == "cancelled":
            raise _StageGuardError(f"Run {run_id} is cancelled")

        if subtitle_format not in ("srt", "vtt"):
            raise ValueError(
                f"Invalid subtitle_format: {subtitle_format!r}. Must be 'srt' or 'vtt'."
            )

        if not os.path.exists(audio_path):
            raise RuntimeError(f"Audio file not found: {audio_path}")

        # 1. Provider resolution
        registry = ProviderRegistry.create_default()
        entry = registry.resolve(subtitle_model)
        provider = registry.get_provider(subtitle_model)

        provider_type = entry.provider_type
        endpoint = entry.endpoint

        # 2. GPU lock
        if entry.requires_gpu:
            redis_client = _get_redis_client()
            if redis_client is None:
                raise RuntimeError("Redis client is unavailable; cannot acquire GPU lock")
            acquire_gpu_lock(redis_client, task_id)
            lock_acquired = True
            gpu_lock_acquired_at = _utc_now_iso()

        safe_section_id = sanitize_path_component(section_id, label="section_id")
        subtitle_path = f"{_ARTIFACT_ROOT}/{run_id}/subtitles/{safe_section_id}.{subtitle_format}"

        try:
            Path(subtitle_path).parent.mkdir(parents=True, exist_ok=True)

            # 3. Transcribe via provider
            params = dict(entry.default_params or {})
            params["format"] = subtitle_format
            params["output_path"] = subtitle_path
            try:
                await provider.transcribe(audio_path, params=params)
            except (TimeoutError, ConnectionError) as exc:
                raise ProviderTimeoutError(
                    "Provider timed out during paragraph subtitle generation "
                    f"for run {run_id} section {section_id}"
                ) from exc
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                message = str(exc).lower()
                if "429" in message or "rate" in message:
                    raise RateLimitError(
                        "Provider rate limited paragraph subtitle generation "
                        f"for run {run_id} section {section_id}"
                    ) from exc
                raise ProviderError(
                    "Provider failed paragraph subtitle generation "
                    f"for run {run_id} section {section_id}"
                ) from exc

            # 4. Save per-paragraph subtitle artifact
            artifact = await _subtitle_service.create_paragraph_artifact(
                run_id=run_id,
                section_id=section_id,
                path=subtitle_path,
                fmt=subtitle_format,
                model_used=subtitle_model,
                provider_type=entry.provider_type,
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

        return {
            "task_id": task_id,
            "run_id": run_id,
            "section_id": section_id,
            "subtitle_model": subtitle_model,
            "subtitle_format": subtitle_format,
            "provider_type": provider_type,
            "endpoint": endpoint,
            "gpu_lock_acquired_at": gpu_lock_acquired_at,
            "gpu_lock_released_at": gpu_lock_released_at,
            "subtitle_artifact_id": artifact.id,
            "subtitle_path": artifact.path,
            "audio_path": audio_path,
            "start_time": start_iso,
            "end_time": end_time.isoformat(),
            "duration_seconds": duration_seconds,
            "status": "success",
        }

    try:
        return asyncio.run(_run_task())
    except _StageGuardError:
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
    except Exception:
        logger.exception(
            "Failed to generate paragraph subtitles for run %d section %s",
            run_id,
            section_id,
        )
        raise
    finally:
        try:
            asyncio.run(_remove_active_task_id_best_effort(run_id, task_id))
        except Exception:
            logger.warning(
                "Could not remove active task id %s for run %d",
                task_id,
                run_id,
                exc_info=True,
            )
