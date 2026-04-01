"""Celery task for run-level TTS audio generation via audio providers.

Consumes an approved script draft and generates a single audio artifact
for the run. The artifact is stored via the audio_service.

Key design decisions:
- Audio generation is all-or-nothing for a run (no partial scene-level success).
- GPU lock is held for the full generation window when required by provider.
- Audio is saved to local filesystem: data/artifacts/{run_id}/audio/audio.wav
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

try:
    import redis
except ImportError:
    redis = None  # type: ignore[assignment]

from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
from creator_provider.registry import ProviderRegistry
from creator_service.audio_service import audio_service as _audio_service
from creator_service.run_service import run_service as _run_service
from creator_service.script_service import script_service as _script_service

logger = logging.getLogger(__name__)

_ALLOWED_STAGES = frozenset({RunStage.VISUAL_ASSET_REVIEW, RunStage.AUDIO_GENERATING})
_ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")

# Stages where writing SUBTITLE_GENERATING or FAILED is safe — the run
# hasn't advanced past audio generation. The task may start directly from
# VISUAL_ASSET_REVIEW or from AUDIO_GENERATING after API-side CAS.
_SAFE_STAGES = frozenset({
    RunStage.VISUAL_ASSET_REVIEW.value,
    RunStage.AUDIO_GENERATING.value,
})


class _StageGuardError(ValueError):
    """Raised when a run is not in an acceptable stage for audio generation.

    This is a validation/rejection error — the run state must NOT be mutated
    to FAILED because the run may already be in a later stage.
    """


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_redis_client() -> Any | None:
    if redis is None:
        return None
    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


async def _remove_active_task_id_best_effort(run_id: int, task_id: str) -> None:
    remover = getattr(_run_service.storage, "remove_active_task_id", None)
    if not callable(remover):
        return
    try:
        await remover(run_id, task_id)
    except Exception:
        logger.exception("Failed to remove active task id %s for run %d", task_id, run_id)


@celery_app.task(bind=True, name="generate_audio")
def generate_audio(
    self,
    run_id: int,
    tts_model: str = "qwen3-tts",
    voice: str = "default",
) -> dict[str, object]:
    start_time = datetime.now(timezone.utc)
    start_iso = start_time.isoformat()
    task_id = str(getattr(getattr(self, "request", None), "id", None) or f"run-{run_id}")

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
                    f"expected one of {', '.join(s for s in _ALLOWED_STAGES)}"
                )

            # 2. Fetch approved script draft.
            draft = await _script_service.get_active_draft(run_id)
            if draft is None:
                raise _StageGuardError(f"No script draft found for run {run_id}")

            script_text = (draft.markdown_content or "").strip()
            if not script_text and draft.structured_script:
                script_text = "\n".join(
                    (section.display_text or section.text).strip()
                    for section in draft.structured_script
                    if (section.display_text or section.text).strip()
                )

            if not script_text:
                raise _StageGuardError(f"Script draft for run {run_id} has no content")

            # 3. Provider resolution (sync — blocks briefly, fine in Celery worker).
            registry = ProviderRegistry.create_default()
            entry = registry.resolve(tts_model)
            provider = registry.get_provider(tts_model)

            provider_type = entry.provider_type
            endpoint = entry.endpoint

            # 4. GPU lock acquisition (sync).
            if entry.requires_gpu:
                redis_client = _get_redis_client()
                if redis_client is None:
                    raise RuntimeError("Redis client is unavailable; cannot acquire GPU lock")
                acquire_gpu_lock(redis_client, task_id)
                lock_acquired = True
                gpu_lock_acquired_at = _utc_now_iso()

            audio_path = f"{_ARTIFACT_ROOT}/{run_id}/audio/audio.wav"

            try:
                os.makedirs(os.path.dirname(audio_path), exist_ok=True)
                # 5. Generate audio via provider.
                params = dict(entry.default_params or {})
                params["output_path"] = audio_path
                await provider.generate(script_text, voice=voice, params=params)

                # 6. Save audio artifact via service.
                artifact = await _audio_service.create_artifact(
                    run_id=run_id,
                    path=audio_path,
                    model_used=tts_model,
                    provider_type=entry.provider_type,
                    voice=voice,
                )

                # 7. Atomic success transition.
                applied, _ = await _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.SUBTITLE_GENERATING,
                        "status": "running",
                    },
                    expected_stages=_SAFE_STAGES,
                )
                if not applied:
                    logger.info(
                        "Run %d stage changed during audio generation -- skipping transition",
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

            return {
                "task_id": task_id,
                "run_id": run_id,
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
        finally:
            await _remove_active_task_id_best_effort(run_id, task_id)

    try:
        return asyncio.run(_run_task())
    except _StageGuardError:
        # Validation rejection — do NOT mutate run state to FAILED.
        raise
    except Exception:
        # Unexpected error — atomic conditional fail.
        try:
            applied, _ = asyncio.run(
                _run_service.storage.conditional_update_run(
                    run_id,
                    {
                        "current_stage": RunStage.FAILED,
                        "status": "failed",
                    },
                    expected_stages=_SAFE_STAGES,
                )
            )
            if not applied:
                logger.info(
                    "Run %d stage changed during audio generation -- skipping FAILED transition",
                    run_id,
                )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after task error", run_id)

        raise
