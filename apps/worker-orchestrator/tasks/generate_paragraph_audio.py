"""Celery task for per-paragraph TTS audio generation.

Generates audio for a single script section (paragraph).  Unlike the
run-level ``generate_audio`` task this does NOT transition stages — the
caller (storyboard API) manages aggregate state.

Audio is saved to: data/artifacts/{run_id}/audio/{section_id}.wav

Idempotency:
    IDEMPOTENT - Safe to retry:
    - Does NOT perform stage guard (paragraph tasks don't manage run stages).
    - Multiple invocations generate NEW artifact records with unique IDs but
      the same section_id. Each invocation overwrites the audio file.
    - Caller is responsible for deduplication (e.g., check if artifact already exists
      before invoking task, or use task ID for idempotency key).
    - Task gracefully handles multiple invocations: later artifacts do not break earlier ones;
      the caller selects the desired artifact by version or timestamp.
    - Idempotency guaranteed by acks_late + task_reject_on_worker_lost for task delivery;
      file overwrites are idempotent (same content each invocation).

Side effects:
    - Filesystem: Saves audio to data/artifacts/{run_id}/audio/{safe_section_id}.wav
      (overwrites on retry).
    - Database: Creates audio artifact record (run_id, section_id, path, model_used,
      provider_type, voice). Each invocation creates a new record.
    - GPU Resource: Acquires/releases GPU lock in Redis (if provider requires GPU).
    - NO stage transition: Caller manages run stages.

Retry safety:
    SAFE FOR RETRY - Configured with:
    - max_retries=3
    - autoretry_for=(ProviderTimeoutError, RateLimitError)
    - retry_backoff=True, retry_jitter=True
    - soft_time_limit=300s, hard time_limit=360s
    On timeout: Task does NOT transition run stage (caller's responsibility).
    Task simply re-raises timeout exception; caller decides whether to transition run to FAILED.
"""

# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

# pyright: reportMissingImports=false

import asyncio
import logging
import os
import wave
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
from creator_domain.sanitize import sanitize_path_component
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
from creator_provider.registry import ProviderRegistry
from creator_service.audio_service import audio_service as _audio_service
from creator_service.cost_config import COST_PARAGRAPH_AUDIO
from creator_service.run_service import run_service as _run_service
from creator_service.telemetry import trace_task
from creator_service.task_tracking_service import task_tracking_service as _task_tracking_service
from creator_service.usage_service import record_provider_call, resolve_workspace_id_from_run

logger = logging.getLogger(__name__)

_ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")

# Stages where a timed-out paragraph task can safely transition the run to FAILED.
# Since paragraph tasks don't manage stages, we include common audio/subtitle stages.
_SAFE_STAGES = frozenset(
    {
        RunStage.AUDIO_GENERATING.value,
        RunStage.SUBTITLE_GENERATING.value,
    }
)


class _StageGuardError(ValueError):
    """Raised when a run is not in an acceptable state for paragraph audio generation."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_redis_client() -> Any | None:
    if redis is None:
        return None
    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


def _get_wav_duration_seconds(path: str) -> float | None:
    try:
        with wave.open(path, "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            if frame_rate <= 0:
                return None
            return wav_file.getnframes() / float(frame_rate)
    except Exception:
        logger.warning("Could not determine audio duration for %s", path, exc_info=True)
        return None



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
            await _task_tracking_service.record_task_start(
                run_id, "generate_paragraph_audio", task_id
            )
            await _task_tracking_service.mark_running(task_id)
        except Exception:
            logger.warning("Failed to record task start", exc_info=True)

        run = await _run_service.storage.get_run(run_id)
        if run is not None and run.get("status") == "cancelled":
            raise _StageGuardError(f"Run {run_id} is cancelled")
        workspace_id = await resolve_workspace_id_from_run(run_id)
        project_id = run.get("project_id") if run else None

        # 1. Provider resolution
        registry = ProviderRegistry.create_default()
        entry = registry.resolve(tts_model)
        provider = registry.get_provider(tts_model)

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
        audio_path = f"{_ARTIFACT_ROOT}/{run_id}/audio/{safe_section_id}.wav"

        try:
            os.makedirs(os.path.dirname(audio_path), exist_ok=True)

            # 3. Generate audio via provider
            params = dict(entry.default_params or {})
            params["output_path"] = audio_path
            try:
                await provider.generate(section_text, voice=voice, params=params)
                try:
                    await record_provider_call(
                        run_id,
                        entry.provider_type,
                        tts_model,
                        "tts",
                        audio_seconds=_get_wav_duration_seconds(audio_path),
                        cost_usd=COST_PARAGRAPH_AUDIO,
                        workspace_id=workspace_id,
                        project_id=project_id,
                    )
                except Exception:
                    logger.warning("Failed to record provider usage", exc_info=True)
            except (TimeoutError, ConnectionError) as exc:
                raise ProviderTimeoutError(
                    "Provider timed out during paragraph audio generation "
                    f"for run {run_id} section {section_id}"
                ) from exc
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                message = str(exc).lower()
                if "429" in message or "rate" in message:
                    raise RateLimitError(
                        "Provider rate limited paragraph audio generation "
                        f"for run {run_id} section {section_id}"
                    ) from exc
                raise ProviderError(
                    "Provider failed paragraph audio generation "
                    f"for run {run_id} section {section_id}"
                ) from exc

            from creator_service.artifact_storage_integration import store_artifact_file

            try:
                uploaded = store_artifact_file(run_id, audio_path, "audio/wav")
            except Exception as exc:
                logger.error(
                    "Failed to upload artifact %s to remote storage: %s",
                    audio_path,
                    exc,
                )
                raise

            storage_provider = uploaded.storage_provider
            storage_key = uploaded.key

            # 4. Save per-paragraph artifact
            artifact = await _audio_service.create_paragraph_artifact(
                run_id=run_id,
                section_id=section_id,
                path=audio_path,
                model_used=tts_model,
                provider_type=entry.provider_type,
                voice=voice,
                storage_provider=storage_provider,
                storage_key=storage_key,
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
            "section_id": section_id,
            "tts_model": tts_model,
            "voice": voice,
            "provider_type": provider_type,
            "endpoint": endpoint,
            "gpu_lock_acquired_at": gpu_lock_acquired_at,
            "gpu_lock_released_at": gpu_lock_released_at,
            "audio_artifact_id": artifact.id,
            "audio_path": artifact.path,
            "start_time": start_iso,
            "end_time": end_time.isoformat(),
            "duration_seconds": duration_seconds,
            "status": "success",
        }

    try:
        return asyncio.run(_run_task())
    except _StageGuardError:
        # Validation rejection — do NOT mutate run state to FAILED.
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
        try:
            asyncio.run(
                _task_tracking_service.mark_failed(task_id, type(exc).__name__, str(exc)[:500])
            )
        except Exception:
            logger.warning("Failed to record task failure", exc_info=True)
        logger.exception(
            "Failed to generate paragraph audio for run %d section %s",
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
