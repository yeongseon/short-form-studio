"""Celery task for run-level video rendering via FFmpeg.

Consumes active visual assets and optional audio/subtitle artifacts,
renders a single MP4 output for the run, and stores it as a video artifact.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_service.audio_service import audio_service as _audio_service
from creator_service.ffmpeg_service import FFmpegService, RenderInput
from creator_service.render_profile import RenderProfile
from creator_service.render_service import render_service as _render_service
from creator_service.run_service import run_service as _run_service
from creator_service.subtitle_service import subtitle_service as _subtitle_service
from creator_service.visual_asset_service import visual_asset_service as _visual_asset_service

logger = logging.getLogger(__name__)

_ALLOWED_STAGES = frozenset({RunStage.RENDER_GENERATING})
_SAFE_STAGES = frozenset({RunStage.RENDER_GENERATING.value})


class _StageGuardError(ValueError):
    pass

# Map profile name → RenderProfile constructor
_PROFILE_REGISTRY: dict[str, object] = {
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

@celery_app.task(bind=True, name="render_video")
def render_video(
    self,
    run_id: int,
    render_profile: str = "shorts_default",
) -> dict[str, object]:
    start_time = datetime.now(timezone.utc)
    start_iso = start_time.isoformat()
    task_id = str(getattr(getattr(self, "request", None), "id", None) or f"run-{run_id}")

    async def _run_task() -> dict[str, object]:
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

        manifest = await _render_service.build_render_manifest(
            run_id,
            _visual_asset_service,
            _audio_service,
            _subtitle_service,
            render_profile_name=render_profile,
        )

        if not manifest["scenes"]:
            raise RuntimeError("No scenes found for render")

        profile_data = manifest["render_profile"]
        scene_count = len(manifest["scenes"])
        image_paths = [Path(scene["asset_path"]) for scene in manifest["scenes"]]
        audio_path = Path(manifest["audio_path"]) if manifest["audio_path"] else None
        subtitle_path = Path(manifest["subtitle_path"]) if manifest["subtitle_path"] else None
        scene_duration = profile_data["max_duration_seconds"] / scene_count
        scene_durations = [scene_duration] * scene_count

        render_input = RenderInput(
            image_paths=image_paths,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            scene_durations=scene_durations,
        )

        output_path = f"data/artifacts/{run_id}/render/output.mp4"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        resolved_profile = _resolve_profile(render_profile)
        ffmpeg = FFmpegService(profile=resolved_profile)
        ffmpeg.render(render_input, Path(output_path))

        artifact = await _render_service.create_artifact(
            run_id=run_id,
            path=output_path,
            render_profile=render_profile,
        )

        applied, _ = await _run_service.storage.conditional_update_run(
            run_id,
            {
                "current_stage": RunStage.FINAL_REVIEW.value,
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

        return {
            "task_id": task_id,
            "run_id": run_id,
            "render_profile": render_profile,
            "video_artifact_id": artifact.id,
            "video_path": artifact.path,
            "scene_count": len(manifest["scenes"]),
            "audio_path": manifest["audio_path"],
            "subtitle_path": manifest["subtitle_path"],
            "start_time": start_iso,
            "end_time": end_time.isoformat(),
            "duration_seconds": duration_seconds,
            "status": "success",
        }

    try:
        return asyncio.run(_run_task())
    except _StageGuardError:
        raise
    except Exception:
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
                    "Run %d stage changed during video render -- skipping FAILED transition",
                    run_id,
                )
        except Exception:
            logger.exception("Failed to mark run %d as FAILED after task error", run_id)

        raise
