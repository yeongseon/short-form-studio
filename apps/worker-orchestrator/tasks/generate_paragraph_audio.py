"""Celery task for per-paragraph TTS audio generation.

Generates audio for a single script section (paragraph).  Unlike the
run-level ``generate_audio`` task this does NOT transition stages — the
caller (storyboard API) manages aggregate state.

Audio is saved to: data/artifacts/{run_id}/audio/{section_id}.wav
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
from creator_provider.gpu_lock import acquire_gpu_lock, release_gpu_lock
from creator_provider.registry import ProviderRegistry
from creator_service.audio_service import audio_service as _audio_service

logger = logging.getLogger(__name__)

_ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_redis_client() -> Any | None:
    if redis is None:
        return None
    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


@celery_app.task(bind=True, name="generate_paragraph_audio")
def generate_paragraph_audio(
    self,
    run_id: int,
    section_id: str,
    section_text: str,
    tts_model: str = "qwen3-tts",
    voice: str = "default",
) -> dict[str, object]:
    """Generate TTS audio for a single paragraph.

    Parameters
    ----------
    run_id : int
        Parent run ID (used for artifact storage path).
    section_id : str
        The ``section_id`` from the structured script.
    section_text : str
        Plain text of the paragraph to synthesise.
    tts_model : str
        Model key from the provider registry.
    voice : str
        Voice identifier for the TTS provider.
    """
    start_time = datetime.now(timezone.utc)
    start_iso = start_time.isoformat()
    task_id = str(getattr(getattr(self, "request", None), "id", None) or f"para-{run_id}-{section_id}")

    provider_type: str | None = None
    endpoint: str | None = None
    gpu_lock_acquired_at: str | None = None
    gpu_lock_released_at: str | None = None
    redis_client: Any | None = None
    lock_acquired = False

    async def _run_task() -> dict[str, object]:
        nonlocal provider_type, endpoint, gpu_lock_acquired_at, gpu_lock_released_at
        nonlocal redis_client, lock_acquired

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

        audio_path = f"{_ARTIFACT_ROOT}/{run_id}/audio/{section_id}.wav"

        try:
            os.makedirs(os.path.dirname(audio_path), exist_ok=True)

            # 3. Generate audio via provider
            params = dict(entry.default_params or {})
            params["output_path"] = audio_path
            await provider.generate(section_text, voice=voice, params=params)

            # 4. Save per-paragraph artifact
            artifact = await _audio_service.create_paragraph_artifact(
                run_id=run_id,
                section_id=section_id,
                path=audio_path,
                model_used=tts_model,
                provider_type=entry.provider_type,
                voice=voice,
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
    except Exception:
        logger.exception(
            "Failed to generate paragraph audio for run %d section %s",
            run_id,
            section_id,
        )
        raise
