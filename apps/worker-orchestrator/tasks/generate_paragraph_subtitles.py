# pyright: reportMissingImports=false
# ruff: noqa: E402

from __future__ import annotations

import logging
import os
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_domain.sanitize import sanitize_path_component
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_provider.registry import get_default_registry
from creator_service.audio_service import audio_service as _audio_service
from creator_service.cost_config import COST_PARAGRAPH_SUBTITLE
from creator_service.subtitle_service import subtitle_service as _subtitle_service
from creator_service.telemetry import trace_task
from creator_service.usage_service import record_provider_call
from tasks.task_runner import (
    GpuLockContext,
    TaskContext,
    TaskResult,
    TaskRunnerConfig,
    run_task,
    validate_artifact_path,
)

logger = logging.getLogger(__name__)
_ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")

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
@trace_task("generate_paragraph_subtitles")
def generate_paragraph_subtitles(
    self,
    run_id: int,
    section_id: str,
    subtitle_model: str = "whisper-small",
    subtitle_format: str = "srt",
) -> dict[str, object]:
    config = TaskRunnerConfig(
        task_name="generate_paragraph_subtitles",
        allowed_stages=frozenset({RunStage.AUDIO_GENERATING, RunStage.SUBTITLE_GENERATING}),
        safe_stages=frozenset(
            {RunStage.AUDIO_GENERATING.value, RunStage.SUBTITLE_GENERATING.value}
        ),
        success_stage=None,
    )

    async def execute(ctx: TaskContext) -> TaskResult:
        if subtitle_format not in ("srt", "vtt"):
            raise ValueError(
                f"Invalid subtitle_format: {subtitle_format!r}. Must be 'srt' or 'vtt'."
            )
        audio_artifact = await _audio_service.get_paragraph_audio(run_id, section_id)
        if audio_artifact is None:
            raise RuntimeError(f"Audio file not found for run {run_id} section {section_id}")
        audio_path = validate_artifact_path(audio_artifact.path, _ARTIFACT_ROOT)
        if not os.path.exists(audio_path):
            raise RuntimeError(f"Audio file not found: {audio_path}")

        registry = get_default_registry()
        entry = registry.resolve(subtitle_model)
        provider = registry.get_provider(subtitle_model)

        lock_id = f"sub-{run_id}-{section_id}"
        gpu_lock = GpuLockContext(ctx.task_id)
        if entry.requires_gpu:
            gpu_lock.acquire(lock_id=lock_id)

        safe_section_id = sanitize_path_component(section_id, label="section_id")
        subtitle_path = f"{_ARTIFACT_ROOT}/{run_id}/subtitles/{safe_section_id}.{subtitle_format}"
        try:
            Path(subtitle_path).parent.mkdir(parents=True, exist_ok=True)
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
                        "Provider rate limited paragraph subtitle generation "
                        f"for run {run_id} section {section_id}"
                    ) from exc
                raise ProviderError(
                    "Provider failed paragraph subtitle generation "
                    f"for run {run_id} section {section_id}"
                ) from exc
        finally:
            if entry.requires_gpu:
                gpu_lock.release(lock_id=lock_id)

        try:
            await record_provider_call(
                run_id,
                entry.provider_type,
                subtitle_model,
                "stt",
                cost_usd=COST_PARAGRAPH_SUBTITLE,
                workspace_id=ctx.workspace_id,
                project_id=ctx.project_id,
                idempotency_key=ctx.task_id,
            )
        except Exception:
            logger.warning("Failed to record provider usage", exc_info=True)

        from creator_service.artifact_storage_integration import store_artifact_file

        uploaded = store_artifact_file(run_id, subtitle_path, f"application/{subtitle_format}")
        artifact = await _subtitle_service.create_paragraph_artifact(
            run_id=run_id,
            section_id=section_id,
            path=subtitle_path,
            fmt=subtitle_format,
            model_used=subtitle_model,
            provider_type=entry.provider_type,
            storage_provider=uploaded.storage_provider,
            storage_key=uploaded.key,
            idempotency_key=ctx.task_id,
        )

        return TaskResult(
            status="success",
            extra={
                "section_id": section_id,
                "subtitle_model": subtitle_model,
                "subtitle_format": subtitle_format,
                "provider_type": entry.provider_type,
                "endpoint": entry.endpoint,
                "gpu_lock_acquired_at": gpu_lock.acquired_at,
                "gpu_lock_released_at": gpu_lock.released_at,
                "subtitle_artifact_id": artifact.id,
                "subtitle_path": artifact.path,
                "audio_path": audio_path,
            },
        )

    return run_task(self, run_id, config, execute)
