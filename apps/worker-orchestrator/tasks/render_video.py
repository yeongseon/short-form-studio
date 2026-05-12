"""Celery task for run-level video rendering via FFmpeg.

Consumes active visual assets and optional audio/subtitle artifacts,
renders a single MP4 output for the run, and stores it as a video artifact.

Phase 9: Supports per-paragraph audio/subtitle concatenation when available.
Falls back to run-level audio/subtitles if per-paragraph artifacts don't exist.

Idempotency:
    IDEMPOTENT - Safe to retry:
    - Stage guard rejects if run has progressed past RENDER_GENERATING.
    - Multiple invocations attempt render; only first successful render and stage
      transition complete (conditional_update_run uses compare-and-set).
    - Subsequent invocations overwrite output video but stage transition no-ops
      if run has already advanced to FINAL_REVIEW.
    - FFmpeg handles multiple invocations gracefully (file overwrites).
    - Idempotency guaranteed by acks_late + task_reject_on_worker_lost.

Side effects:
    - Filesystem: Saves video to data/artifacts/{run_id}/render/output.mp4 (overwrites on retry).
    - Filesystem: Creates intermediate audio/subtitle concatenated files in render/ dir
      (audio_concat.wav, subtitles_merged.srt).
    - Database: Creates video artifact record (run_id, path, render_profile).
    - Database: Atomically transitions run stage to FINAL_REVIEW (via conditional_update_run).
    - No GPU resource: FFmpeg runs CPU-only (no lock management).

Retry safety:
    SAFE FOR RETRY - Configured with:
    - max_retries=3
    - autoretry_for=(ProviderTimeoutError, RateLimitError)
    - retry_backoff=True, retry_jitter=True
    - soft_time_limit=600s, hard time_limit=660s (longest of all tasks)
    On timeout: Task transitions run to FAILED atomically before raising.
    On partial failure (missing audio/subtitles): Task falls back gracefully to run-level
    artifacts; logs warnings but completes (no exception).
"""

# pyright: reportMissingImports=false

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_service.audio_service import audio_service as _audio_service
from creator_service.cost_config import COST_RENDER_VIDEO
from creator_service.ffmpeg_service import FFmpegService, RenderInput
from creator_service.render_profile import RenderProfile
from creator_service.render_service import render_service as _render_service
from creator_service.run_service import run_service as _run_service
from creator_service.script_service import script_service as _script_service
from creator_service.subtitle_service import subtitle_service as _subtitle_service
from creator_service.telemetry import trace_task
from creator_service.task_tracking_service import task_tracking_service as _task_tracking_service
from creator_service.usage_service import record_provider_call, resolve_workspace_id_from_run
from creator_service.visual_asset_service import visual_asset_service as _visual_asset_service
from creator_service.visual_plan_service import visual_plan_service as _visual_plan_service

logger = logging.getLogger(__name__)

_ALLOWED_STAGES = frozenset({RunStage.RENDER_GENERATING})
_SAFE_STAGES = frozenset({RunStage.RENDER_GENERATING})
_ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")


class _StageGuardError(ValueError):
    pass


# Map profile name → RenderProfile constructor
_PROFILE_REGISTRY: dict[str, Callable[[], RenderProfile]] = {
    "shorts_default": RenderProfile.default,
    "high_quality": RenderProfile.high_quality,
    "fast_preview": RenderProfile.fast_preview,
}


def _resolve_profile(name: str) -> RenderProfile:
    factory = _PROFILE_REGISTRY.get(name)
    if factory is None:
        logger.warning("Unknown render profile %r, falling back to default", name)
        return RenderProfile.default()
    return factory()


@celery_app.task(
    bind=True,
    autoretry_for=(ProviderTimeoutError, RateLimitError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=600,
    time_limit=660,
    name="render_video",
)
@trace_task("render_video")
def render_video(
    self,
    run_id: int,
    render_profile: str = "shorts_default",
) -> dict[str, object]:
    start_time = datetime.now(timezone.utc)
    start_iso = start_time.isoformat()
    task_id = str(getattr(getattr(self, "request", None), "id", None) or f"run-{run_id}")
    # Idempotency: acks_late + task_reject_on_worker_lost ensures redelivery on crash.
    # If the run has already advanced past this stage, the worker's stage check will
    # naturally skip processing (handled by run_service stage validation).

    async def _run_task() -> dict[str, object]:
        try:
            try:
                await _task_tracking_service.record_task_start(run_id, "render_video", task_id)
                await _task_tracking_service.mark_running(task_id)
            except Exception:
                logger.warning("Failed to record task start", exc_info=True)
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
            if run.get("status") == "cancelled":
                raise _StageGuardError(f"Run {run_id} is cancelled")
            workspace_id = await resolve_workspace_id_from_run(run_id)
            project_id = run.get("project_id")

            manifest = await _render_service.build_render_manifest(
                run_id,
                _visual_asset_service,
                _audio_service,
                _subtitle_service,
                render_profile_name=render_profile,
            )

            active_plan = await _visual_plan_service.get_active_plan(run_id)
            if active_plan is not None:
                scenes_by_id = {scene["scene_id"]: scene for scene in manifest["scenes"]}
                ordered_scenes = [
                    scenes_by_id[scene.scene_id]
                    for scene in active_plan.scenes
                    if scene.scene_id in scenes_by_id
                ]
                remaining_scenes = [
                    scene
                    for scene in manifest["scenes"]
                    if scene["scene_id"] not in {ordered["scene_id"] for ordered in ordered_scenes}
                ]
                manifest["scenes"] = ordered_scenes + remaining_scenes

            if not manifest["scenes"]:
                raise RuntimeError("No scenes found for render")

            profile_data = manifest["render_profile"]
            scene_count = len(manifest["scenes"])
            image_paths = [Path(scene["asset_path"]) for scene in manifest["scenes"]]

            resolved_profile = _resolve_profile(render_profile)
            ffmpeg = FFmpegService(profile=resolved_profile)

            paragraph_audio = await _audio_service.list_paragraph_audio(run_id)
            paragraph_subtitles = await _subtitle_service.list_paragraph_subtitles(run_id)
            run_audio_path = manifest["audio_path"]
            run_sub_path = manifest["subtitle_path"]

            audio_path: Path | None = None
            subtitle_path: Path | None = None
            scene_durations: list[float]

            if paragraph_audio:
                audio_by_section: dict[str, Any] = {}
                for a in paragraph_audio:
                    if a.section_id and a.section_id not in audio_by_section:
                        audio_by_section[a.section_id] = a

                draft = await _script_service.get_active_draft(run_id)
                if draft and draft.structured_script:
                    ordered_sections = [s.section_id for s in draft.structured_script]
                else:
                    ordered_sections = list(audio_by_section.keys())

                all_audio_covered = bool(ordered_sections) and all(
                    sid in audio_by_section for sid in ordered_sections
                )
                if all_audio_covered:
                    ordered_audio_paths = [audio_by_section[sid].path for sid in ordered_sections]
                    duration_by_section: dict[str, float] = {}
                    for sid in ordered_sections:
                        art = audio_by_section[sid]
                        try:
                            duration_by_section[sid] = ffmpeg.get_audio_duration(art.path)
                        except Exception:
                            logger.warning(
                                "Failed to probe duration for %s, using 5.0s fallback",
                                art.path,
                            )
                            duration_by_section[sid] = 5.0

                    concat_path = f"{_ARTIFACT_ROOT}/{run_id}/render/audio_concat.wav"
                    ffmpeg.concatenate_audio(ordered_audio_paths, concat_path)
                    audio_path = Path(concat_path)

                    scene_durations = [duration_by_section[sid] for sid in ordered_sections][
                        :scene_count
                    ]
                    if len(scene_durations) < scene_count:
                        total_known = sum(scene_durations)
                        remaining = max(0.0, profile_data["max_duration_seconds"] - total_known)
                        missing = scene_count - len(scene_durations)
                        pad_dur = remaining / missing if missing > 0 else 5.0
                        scene_durations.extend([pad_dur] * missing)

                    subtitle_path = Path(run_sub_path) if run_sub_path else None
                    if paragraph_subtitles:
                        sub_by_section: dict[str, Any] = {}
                        for s in paragraph_subtitles:
                            if s.section_id and s.section_id not in sub_by_section:
                                sub_by_section[s.section_id] = s

                        all_subtitles_covered = bool(ordered_sections) and all(
                            sid in sub_by_section for sid in ordered_sections
                        )
                        if all_subtitles_covered:
                            ordered_sub_paths = [
                                sub_by_section[sid].path for sid in ordered_sections
                            ]
                            ordered_sub_durations = [
                                duration_by_section[sid] for sid in ordered_sections
                            ]
                            merged_sub_path = (
                                f"{_ARTIFACT_ROOT}/{run_id}/render/subtitles_merged.srt"
                            )
                            ffmpeg.merge_subtitles(
                                ordered_sub_paths, ordered_sub_durations, merged_sub_path
                            )
                            subtitle_path = Path(merged_sub_path)
                        else:
                            logger.warning(
                                "Run %d: paragraph subtitles incomplete (%d/%d sections), falling back to run-level subtitles",
                                run_id,
                                len(sub_by_section),
                                len(ordered_sections),
                            )
                else:
                    logger.warning(
                        "Run %d: paragraph audio incomplete (%d/%d sections), falling back to run-level audio",
                        run_id,
                        len(audio_by_section),
                        len(ordered_sections),
                    )
                    audio_path = Path(run_audio_path) if run_audio_path else None
                    subtitle_path = Path(run_sub_path) if run_sub_path else None
                    scene_duration = profile_data["max_duration_seconds"] / scene_count
                    scene_durations = [scene_duration] * scene_count
            else:
                audio_path = Path(run_audio_path) if run_audio_path else None
                subtitle_path = Path(run_sub_path) if run_sub_path else None
                scene_duration = profile_data["max_duration_seconds"] / scene_count
                scene_durations = [scene_duration] * scene_count

            render_input = RenderInput(
                image_paths=image_paths,
                audio_path=audio_path,
                subtitle_path=subtitle_path,
                scene_durations=scene_durations,
            )

            output_path = f"{_ARTIFACT_ROOT}/{run_id}/render/output.mp4"
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            try:
                ffmpeg.render(render_input, Path(output_path))
            except (TimeoutError, ConnectionError) as exc:
                raise ProviderTimeoutError(
                    f"Provider timed out during video render for run {run_id}"
                ) from exc
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                message = str(exc).lower()
                if "429" in message or "rate" in message:
                    raise RateLimitError(
                        f"Provider rate limited video render for run {run_id}"
                    ) from exc
                raise ProviderError(f"Provider failed video render for run {run_id}") from exc
            try:
                await record_provider_call(
                    run_id,
                    "ffmpeg",
                    render_profile,
                    "render",
                    cost_usd=COST_RENDER_VIDEO,
                    workspace_id=workspace_id,
                    project_id=project_id,
                )
            except Exception:
                logger.warning("Failed to record provider usage", exc_info=True)

            from creator_service.artifact_storage_integration import store_artifact_file

            try:
                uploaded = store_artifact_file(run_id, output_path, "video/mp4")
            except Exception as exc:
                logger.error(
                    "Failed to upload artifact %s to remote storage: %s",
                    output_path,
                    exc,
                )
                raise

            storage_provider = uploaded.storage_provider
            storage_key = uploaded.key

            try:
                artifact = await _render_service.create_artifact(
                    run_id=run_id,
                    path=output_path,
                    render_profile=render_profile,
                    storage_provider=storage_provider,
                    storage_key=storage_key,
                )
            except TypeError:
                artifact = await _render_service.create_artifact(
                    run_id=run_id,
                    path=output_path,
                    render_profile=render_profile,
                )

            applied, _ = await _run_service.storage.conditional_update_run(
                run_id,
                {
                    "current_stage": RunStage.FINAL_REVIEW,
                    "status": "running",
                },
                expected_stages=_SAFE_STAGES,
            )
            if not applied:
                logger.info(
                    "Run %d stage changed during video render -- skipping transition",
                    run_id,
                )

            end_time = datetime.now(timezone.utc)
            duration_seconds = (end_time - start_time).total_seconds()
            try:
                await _task_tracking_service.mark_success(task_id)
            except Exception:
                logger.warning("Failed to record task success", exc_info=True)

            return {
                "task_id": task_id,
                "run_id": run_id,
                "render_profile": render_profile,
                "video_artifact_id": artifact.id,
                "video_path": artifact.path,
                "scene_count": len(manifest["scenes"]),
                "audio_path": str(audio_path) if audio_path else None,
                "subtitle_path": str(subtitle_path) if subtitle_path else None,
                "start_time": start_iso,
                "end_time": end_time.isoformat(),
                "duration_seconds": duration_seconds,
                "status": "success",
            }
        finally:
            pass

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
        if (
            isinstance(exc, (ProviderTimeoutError, RateLimitError))
            and self.request.retries < self.max_retries
        ):
            raise
        try:
            asyncio.run(
                _task_tracking_service.mark_failed(task_id, type(exc).__name__, str(exc)[:500])
            )
        except Exception:
            logger.warning("Failed to record task failure", exc_info=True)
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
                    "Run %d stage changed during video render -- skipping FAILED transition",
                    run_id,
                )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after task error", run_id)

        raise
