"""Celery task for run-level video rendering via FFmpeg.

Consumes active visual assets and optional audio/subtitle artifacts,
renders a single MP4 output for the run, and stores it as a video artifact.

Phase 9: Supports per-paragraph audio/subtitle concatenation when available.
Falls back to run-level audio/subtitles if per-paragraph artifacts don't exist.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_service.audio_service import audio_service as _audio_service
from creator_service.ffmpeg_service import FFmpegService, RenderInput
from creator_service.render_profile import RenderProfile
from creator_service.render_service import render_service as _render_service
from creator_service.run_service import run_service as _run_service
from creator_service.subtitle_service import subtitle_service as _subtitle_service
from creator_service.visual_asset_service import visual_asset_service as _visual_asset_service
from creator_service.script_service import script_service as _script_service

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
                f"expected one of {', '.join(s for s in _ALLOWED_STAGES)}"
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

        resolved_profile = _resolve_profile(render_profile)
        ffmpeg = FFmpegService(profile=resolved_profile)

        # --- Per-paragraph audio/subtitle assembly (Phase 9) -----------------
        # Try per-paragraph artifacts first; fall back to run-level.
        paragraph_audio = await _audio_service.list_paragraph_audio(run_id)
        paragraph_subtitles = await _subtitle_service.list_paragraph_subtitles(run_id)

        audio_path: Path | None = None
        subtitle_path: Path | None = None
        scene_durations: list[float]

        if paragraph_audio:
            # Build section_id -> audio mapping
            audio_by_section: dict[str, Any] = {}
            for a in paragraph_audio:
                if a.section_id and a.section_id not in audio_by_section:
                    audio_by_section[a.section_id] = a

            # Get section order from script
            draft = await _script_service.get_active_draft(run_id)
            if draft and draft.structured_script:
                ordered_sections = [s.section_id for s in draft.structured_script]
            else:
                ordered_sections = sorted(audio_by_section.keys())

            # Collect audio files and durations in section order
            ordered_audio_paths: list[str] = []
            ordered_durations: list[float] = []
            for sid in ordered_sections:
                art = audio_by_section.get(sid)
                if art:
                    ordered_audio_paths.append(art.path)
                    try:
                        dur = ffmpeg.get_audio_duration(art.path)
                    except Exception:
                        logger.warning(
                            "Failed to probe duration for %s, using 5.0s fallback",
                            art.path,
                        )
                        dur = 5.0
                    ordered_durations.append(dur)

            if ordered_audio_paths:
                # Concatenate per-paragraph audio into a single file
                concat_path = f"{_ARTIFACT_ROOT}/{run_id}/render/audio_concat.wav"
                ffmpeg.concatenate_audio(ordered_audio_paths, concat_path)
                audio_path = Path(concat_path)

                # Use actual per-paragraph durations for scene timing
                scene_durations = ordered_durations[:scene_count]
                # If fewer durations than scenes, pad with equal split of remaining time
                if len(scene_durations) < scene_count:
                    total_known = sum(scene_durations)
                    remaining = max(0.0, profile_data["max_duration_seconds"] - total_known)
                    missing = scene_count - len(scene_durations)
                    pad_dur = remaining / missing if missing > 0 else 5.0
                    scene_durations.extend([pad_dur] * missing)
            else:
                # No matched audio — fall back to equal split
                scene_duration = profile_data["max_duration_seconds"] / scene_count
                scene_durations = [scene_duration] * scene_count

            # Merge per-paragraph subtitles if available
            if paragraph_subtitles:
                sub_by_section: dict[str, Any] = {}
                for s in paragraph_subtitles:
                    if s.section_id and s.section_id not in sub_by_section:
                        sub_by_section[s.section_id] = s

                ordered_sub_paths: list[str] = []
                ordered_sub_durations: list[float] = []
                for sid in ordered_sections:
                    sub = sub_by_section.get(sid)
                    if sub:
                        ordered_sub_paths.append(sub.path)
                        # Use same duration as audio
                        art = audio_by_section.get(sid)
                        ordered_sub_durations.append(
                            ordered_durations[ordered_sections.index(sid)]
                            if sid in audio_by_section and ordered_durations
                            else 5.0
                        )

                if ordered_sub_paths:
                    merged_sub_path = f"{_ARTIFACT_ROOT}/{run_id}/render/subtitles_merged.srt"
                    ffmpeg.merge_subtitles(
                        ordered_sub_paths, ordered_sub_durations, merged_sub_path
                    )
                    subtitle_path = Path(merged_sub_path)
        else:
            # No per-paragraph audio — fall back to run-level artifacts
            run_audio_path = manifest["audio_path"]
            audio_path = Path(run_audio_path) if run_audio_path else None
            run_sub_path = manifest["subtitle_path"]
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
