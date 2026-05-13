# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

import logging
import os
import wave
from typing import Any

redis: Any
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
from creator_service.usage_service import record_provider_call
from tasks import task_runner as _task_runner
from tasks.task_runner import GpuLockContext, TaskContext, TaskResult, TaskRunnerConfig, run_task

logger = logging.getLogger(__name__)
_ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")


def _sync_runner_dependencies() -> None:
    _task_runner._run_service = _run_service
    _task_runner.redis = redis
    _task_runner.acquire_gpu_lock = acquire_gpu_lock
    _task_runner.release_gpu_lock = release_gpu_lock


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
    name="generate_paragraph_audio",
)
@trace_task("generate_paragraph_audio")
def generate_paragraph_audio(
    self,
    run_id: int,
    section_id: str,
    tts_model: str = "qwen3-tts",
    voice: str = "default",
) -> dict[str, object]:
    _sync_runner_dependencies()
    config = TaskRunnerConfig(
        task_name="generate_paragraph_audio",
        allowed_stages=frozenset({RunStage.AUDIO_GENERATING, RunStage.SUBTITLE_GENERATING}),
        safe_stages=frozenset(
            {RunStage.AUDIO_GENERATING.value, RunStage.SUBTITLE_GENERATING.value}
        ),
        success_stage=None,
        skip_stage_guard=True,
    )

    async def execute(ctx: TaskContext) -> TaskResult:
        run = await _run_service.storage.get_run(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")
        script_data = run.get("script_data") or {}
        sections = script_data.get("sections") if isinstance(script_data, dict) else []
        section_text: str | None = None
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    continue
                if section.get("section_id") == section_id:
                    raw_text = section.get("text")
                    if isinstance(raw_text, str):
                        section_text = raw_text
                    break
        if section_text is None:
            raise ValueError(f"Section '{section_id}' not found for run {run_id}")

        registry = ProviderRegistry.create_default()
        entry = registry.resolve(tts_model)
        provider = registry.get_provider(tts_model)
        lock_id = f"para-{run_id}-{section_id}"
        gpu_lock = GpuLockContext(ctx.task_id)
        if entry.requires_gpu:
            gpu_lock.acquire(lock_id=lock_id)

        safe_section_id = sanitize_path_component(section_id, label="section_id")
        audio_path = f"{_ARTIFACT_ROOT}/{run_id}/audio/{safe_section_id}.wav"
        try:
            os.makedirs(os.path.dirname(audio_path), exist_ok=True)
            params = dict(entry.default_params or {})
            params["output_path"] = audio_path
            try:
                await provider.generate(section_text, voice=voice, params=params)
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
        finally:
            if entry.requires_gpu:
                gpu_lock.release(lock_id=lock_id)

        try:
            await record_provider_call(
                run_id,
                entry.provider_type,
                tts_model,
                "tts",
                audio_seconds=_get_wav_duration_seconds(audio_path),
                cost_usd=COST_PARAGRAPH_AUDIO,
                workspace_id=ctx.workspace_id,
                project_id=ctx.project_id,
            )
        except Exception:
            logger.warning("Failed to record provider usage", exc_info=True)

        from creator_service.artifact_storage_integration import store_artifact_file

        uploaded = store_artifact_file(run_id, audio_path, "audio/wav")
        try:
            artifact = await _audio_service.create_paragraph_artifact(
                run_id=run_id,
                section_id=section_id,
                path=audio_path,
                model_used=tts_model,
                provider_type=entry.provider_type,
                voice=voice,
                storage_provider=uploaded.storage_provider,
                storage_key=uploaded.key,
            )
        except TypeError:
            artifact = await _audio_service.create_paragraph_artifact(
                run_id=run_id,
                section_id=section_id,
                path=audio_path,
                model_used=tts_model,
                provider_type=entry.provider_type,
                voice=voice,
            )

        return TaskResult(
            status="success",
            extra={
                "section_id": section_id,
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
