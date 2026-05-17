# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

import logging
import os
import wave


from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_provider.registry import ProviderRegistry
from creator_service.audio_service import audio_service as _audio_service
from creator_service.cost_config import COST_AUDIO_GENERATION
from creator_service.script_service import script_service as _script_service
from creator_service.telemetry import trace_task
from creator_service.usage_service import record_provider_call
from tasks.task_runner import GpuLockContext, TaskContext, TaskResult, TaskRunnerConfig, run_task

logger = logging.getLogger(__name__)
_ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")

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

@celery_app.task(
    bind=True,
    autoretry_for=(ProviderTimeoutError, RateLimitError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=300,
    time_limit=360,
    name="generate_audio",
)
@trace_task("generate_audio")
def generate_audio(
    self,
    run_id: int,
    tts_model: str = "qwen3-tts",
    voice: str = "default",
) -> dict[str, object]:
    config = TaskRunnerConfig(
        task_name="generate_audio",
        allowed_stages=frozenset({RunStage.VISUAL_ASSET_REVIEW, RunStage.AUDIO_GENERATING}),
        safe_stages=frozenset(
            {RunStage.VISUAL_ASSET_REVIEW.value, RunStage.AUDIO_GENERATING.value}
        ),
        success_stage=RunStage.SUBTITLE_GENERATING.value,
    )

    async def execute(ctx: TaskContext) -> TaskResult:
        draft = await _script_service.get_active_draft(run_id)
        if draft is None:
            raise ValueError(f"No script draft found for run {run_id}")

        script_text = (draft.markdown_content or "").strip()
        if not script_text and draft.structured_script:
            script_text = "\n".join(
                (section.display_text or section.text).strip()
                for section in draft.structured_script
                if (section.display_text or section.text).strip()
            )
        if not script_text:
            raise ValueError(f"Script draft for run {run_id} has no content")

        registry = ProviderRegistry.create_default()
        entry = registry.resolve(tts_model)
        provider = registry.get_provider(tts_model)

        gpu_lock = GpuLockContext(ctx.task_id)
        if entry.requires_gpu:
            gpu_lock.acquire()

        audio_path = f"{_ARTIFACT_ROOT}/{run_id}/audio/audio.wav"
        try:
            os.makedirs(os.path.dirname(audio_path), exist_ok=True)
            params = dict(entry.default_params or {})
            params["output_path"] = audio_path
            try:
                await provider.generate(script_text, voice=voice, params=params)
            except (TimeoutError, ConnectionError) as exc:
                raise ProviderTimeoutError(
                    f"Provider timed out during audio generation for run {run_id}"
                ) from exc
            except ProviderTimeoutError:
                raise
            except RateLimitError:
                raise
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                message = str(exc).lower()
                if "429" in message or "rate" in message:
                    raise RateLimitError(
                        f"Provider rate limited audio generation for run {run_id}"
                    ) from exc
                raise ProviderError(f"Provider failed audio generation for run {run_id}") from exc
        finally:
            if entry.requires_gpu:
                gpu_lock.release()

        try:
            await record_provider_call(
                run_id,
                entry.provider_type,
                tts_model,
                "tts",
                audio_seconds=_get_wav_duration_seconds(audio_path),
                cost_usd=COST_AUDIO_GENERATION,
                workspace_id=ctx.workspace_id,
                project_id=ctx.project_id,
                idempotency_key=ctx.task_id,
            )
        except Exception:
            logger.warning("Failed to record provider usage", exc_info=True)

        from creator_service.artifact_storage_integration import store_artifact_file

        uploaded = store_artifact_file(run_id, audio_path, "audio/wav")
        artifact = await _audio_service.create_artifact(
            run_id=run_id,
            path=audio_path,
            model_used=tts_model,
            provider_type=entry.provider_type,
            voice=voice,
            storage_provider=uploaded.storage_provider,
            storage_key=uploaded.key,
            idempotency_key=ctx.task_id,
        )

        return TaskResult(
            status="success",
            extra={
                "tts_model": tts_model,
                "voice": voice,
                "provider_type": entry.provider_type,
                "endpoint": entry.endpoint,
                "gpu_lock_acquired_at": gpu_lock.acquired_at,
                "gpu_lock_released_at": gpu_lock.released_at,
                "audio_artifact_id": artifact.id,
                "audio_path": artifact.path,
            },
        )

    return run_task(self, run_id, config, execute)
