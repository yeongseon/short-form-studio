# pyright: reportMissingImports=false
"""Celery task for run-level subtitle generation via subtitle providers.

Consumes an approved script draft AND optionally audio artifact timing data
and generates a single subtitle artifact for the run (SRT format).

Key design decisions:
- Subtitle generation is all-or-nothing for a run (no partial scene-level success).
- GPU lock is held for the full generation window when required by provider.
- Subtitles are saved to local filesystem: data/artifacts/{run_id}/subtitles/subtitles.srt
"""

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
    from creator_service.subtitle_service import subtitle_service as _subtitle_service
except ImportError:
    from subtitle_service import subtitle_service as _subtitle_service

try:
    from creator_service.script_service import script_service as _script_service
except ImportError:
    from script_service import script_service as _script_service

try:
    from creator_service.audio_service import audio_service as _audio_service
except ImportError:
    from audio_service import audio_service as _audio_service

logger = logging.getLogger(__name__)

_ALLOWED_STAGES = frozenset({RunStage.AUDIO_GENERATING, RunStage.SUBTITLE_GENERATING})

# Stages where writing RENDER_GENERATING or FAILED is safe — the run
# hasn't advanced past subtitle generation.
_SAFE_STAGES = frozenset({RunStage.AUDIO_GENERATING.value, RunStage.SUBTITLE_GENERATING.value})


class _StageGuardError(ValueError):
    """Raised when a run is not in an acceptable stage for subtitle generation.

    This is a validation/rejection error — the run state must NOT be mutated
    to FAILED because the run may already be in a later stage.
    """


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_redis_client() -> Any | None:
    if redis is None:
        return None
    return redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))


@celery_app.task(bind=True, name="generate_subtitles")
def generate_subtitles(
    self,
    run_id: int,
    subtitle_model: str = "whisper-tiny",
    subtitle_format: str = "srt",
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

        # 3. Fetch latest audio artifact (optional timing context).
        audio_artifact = await _audio_service.get_latest(run_id)
        audio_path = audio_artifact.path if audio_artifact else None

        # 4. Provider resolution (sync — blocks briefly, fine in Celery worker).
        registry = ProviderRegistry.create_default()
        entry = registry.resolve(subtitle_model)
        provider = registry.get_provider(subtitle_model)

        provider_type = entry.provider_type
        endpoint = entry.endpoint

        # 5. GPU lock acquisition (sync).
        if entry.requires_gpu:
            redis_client = _get_redis_client()
            if redis_client is None:
                raise RuntimeError("Redis client is unavailable; cannot acquire GPU lock")
            acquire_gpu_lock(redis_client, task_id)
            lock_acquired = True
            gpu_lock_acquired_at = _utc_now_iso()

        subtitle_path = f"data/artifacts/{run_id}/subtitles/subtitles.{subtitle_format}"

        try:
            # 6. Generate subtitles via provider.
            params = dict(entry.default_params or {})
            params["format"] = subtitle_format
            params["output_path"] = subtitle_path
            if audio_path:
                params["audio_path"] = audio_path
            await provider.generate(script_text, params)

            # 7. Save subtitle artifact via service.
            artifact = await _subtitle_service.create_artifact(
                run_id=run_id,
                path=subtitle_path,
                format=subtitle_format,
                model_used=subtitle_model,
                provider_type=entry.provider_type,
            )

            # 8. Atomic success transition.
            applied, _ = await _run_service.storage.conditional_update_run(
                run_id,
                {
                    "current_stage": RunStage.RENDER_GENERATING.value,
                    "status": "running",
                },
                expected_stages=_SAFE_STAGES,
            )
            if not applied:
                logger.info(
                    "Run %d stage changed during subtitle generation -- skipping transition",
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
        # Validation rejection — do NOT mutate run state to FAILED.
        raise
    except Exception:
        # Unexpected error — atomic conditional fail.
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
                    "Run %d stage changed during subtitle generation -- skipping FAILED transition",
                    run_id,
                )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after task error", run_id)

        raise
