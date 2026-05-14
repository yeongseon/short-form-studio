# pyright: reportMissingImports=false

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from celery_app import celery_app
from creator_domain.models.stage import RunStage
from creator_domain.sanitize import UnsafePathComponent, validate_artifact_path
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
from creator_service.usage_service import record_provider_call
from creator_service.visual_asset_service import visual_asset_service as _visual_asset_service
from creator_service.visual_plan_service import visual_plan_service as _visual_plan_service
from tasks import task_runner as _task_runner
from tasks.task_runner import TaskContext, TaskResult, TaskRunnerConfig, run_task

logger = logging.getLogger(__name__)
_ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")
_ALLOWED_RENDER_PROFILE_KEYS: dict[str, type[Any] | tuple[type[Any], ...]] = {
    "name": str,
    "width": int,
    "height": int,
    "fps": int,
    "video_codec": str,
    "audio_codec": str,
    "transition_style": str,
    "min_duration_seconds": (int, float),
    "max_duration_seconds": (int, float),
    "crf": int,
    "preset": str,
    "burn_subtitles": bool,
    "subtitle_font_size": int,
    "resolution": str,
    "codec": str,
    "bitrate": str,
}
_PROFILE_REGISTRY: dict[str, Callable[[], RenderProfile]] = {
    "shorts_default": RenderProfile.default,
    "high_quality": RenderProfile.high_quality,
    "fast_preview": RenderProfile.fast_preview,
}


def _sync_runner_dependencies() -> None:
    _task_runner._run_service = _run_service


def _resolve_profile(name: str) -> RenderProfile:
    factory = _PROFILE_REGISTRY.get(name)
    if factory is None:
        logger.warning("Unknown render profile %r, falling back to default", name)
        return RenderProfile.default()
    return factory()


def _validate_manifest_render_profile(raw_profile: Any) -> dict[str, Any]:
    if not isinstance(raw_profile, dict):
        raise RuntimeError("Invalid render_profile: expected object")

    unknown = set(raw_profile.keys()) - set(_ALLOWED_RENDER_PROFILE_KEYS.keys())
    if unknown:
        raise RuntimeError(f"Invalid render_profile: unknown keys {sorted(unknown)!r}")

    for key, value in raw_profile.items():
        expected_type = _ALLOWED_RENDER_PROFILE_KEYS[key]
        if not isinstance(value, expected_type):
            raise RuntimeError(
                f"Invalid render_profile: key {key!r} has invalid type {type(value).__name__}"
            )

    return raw_profile


def _validate_manifest_path(path: str) -> None:
    validate_artifact_path(path, _ARTIFACT_ROOT)


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
def render_video(self, run_id: int, render_profile: str = "shorts_default") -> dict[str, object]:
    _sync_runner_dependencies()
    config = TaskRunnerConfig(
        task_name="render_video",
        allowed_stages=frozenset({RunStage.RENDER_GENERATING}),
        safe_stages=frozenset({RunStage.RENDER_GENERATING.value}),
        success_stage=RunStage.FINAL_REVIEW.value,
    )

    async def execute(ctx: TaskContext) -> TaskResult:
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

        profile_data = _validate_manifest_render_profile(manifest["render_profile"])
        scene_count = len(manifest["scenes"])
        image_paths: list[Path] = []
        for scene in manifest["scenes"]:
            asset_path = str(scene["asset_path"])
            try:
                _validate_manifest_path(asset_path)
                image_paths.append(Path(asset_path))
            except UnsafePathComponent as exc:
                raise RuntimeError(
                    f"Unsafe manifest path for run {run_id}: scene asset_path {asset_path!r}"
                ) from exc
        ffmpeg = FFmpegService(profile=_resolve_profile(render_profile))

        paragraph_audio = await _audio_service.list_paragraph_audio(run_id)
        paragraph_subtitles = await _subtitle_service.list_paragraph_subtitles(run_id)
        run_audio_path = manifest["audio_path"]
        run_sub_path = manifest["subtitle_path"]
        if run_audio_path:
            try:
                _validate_manifest_path(str(run_audio_path))
            except UnsafePathComponent as exc:
                raise RuntimeError(
                    f"Unsafe manifest path for run {run_id}: audio_path {run_audio_path!r}"
                ) from exc
        if run_sub_path:
            try:
                _validate_manifest_path(str(run_sub_path))
            except UnsafePathComponent as exc:
                raise RuntimeError(
                    f"Unsafe manifest path for run {run_id}: subtitle_path {run_sub_path!r}"
                ) from exc
        audio_path: Path | None = None
        subtitle_path: Path | None = None

        if paragraph_audio:
            audio_by_section: dict[str, Any] = {}
            for a in paragraph_audio:
                if a.section_id and a.section_id not in audio_by_section:
                    audio_by_section[a.section_id] = a
            draft = await _script_service.get_active_draft(run_id)
            ordered_sections = (
                [s.section_id for s in draft.structured_script]
                if draft and draft.structured_script
                else list(audio_by_section.keys())
            )
            all_audio_covered = bool(ordered_sections) and all(
                sid in audio_by_section for sid in ordered_sections
            )
            if all_audio_covered:
                ordered_audio_paths: list[str] = []
                validated_audio_by_section: dict[str, str] = {}
                for sid in ordered_sections:
                    raw_audio_path = str(audio_by_section[sid].path)
                    try:
                        _validate_manifest_path(raw_audio_path)
                        ordered_audio_paths.append(raw_audio_path)
                        validated_audio_by_section[sid] = raw_audio_path
                    except UnsafePathComponent as exc:
                        raise RuntimeError(
                            f"Unsafe manifest path for run {run_id}: paragraph audio path {raw_audio_path!r}"
                        ) from exc
                duration_by_section: dict[str, float] = {}
                for sid in ordered_sections:
                    try:
                        duration_by_section[sid] = ffmpeg.get_audio_duration(
                            validated_audio_by_section[sid]
                        )
                    except Exception:
                        duration_by_section[sid] = 5.0
                concat_path = f"{_ARTIFACT_ROOT}/{run_id}/render/audio_concat.wav"
                ffmpeg.concatenate_audio(ordered_audio_paths, concat_path)
                audio_path = Path(concat_path)
                scene_durations = [duration_by_section[sid] for sid in ordered_sections][
                    :scene_count
                ]
                if len(scene_durations) < scene_count:
                    scene_durations.extend([5.0] * (scene_count - len(scene_durations)))
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
                        merged_sub_path = f"{_ARTIFACT_ROOT}/{run_id}/render/subtitles_merged.srt"
                        merged_sub_inputs: list[str] = []
                        for sid in ordered_sections:
                            raw_subtitle_path = str(sub_by_section[sid].path)
                            try:
                                _validate_manifest_path(raw_subtitle_path)
                                merged_sub_inputs.append(raw_subtitle_path)
                            except UnsafePathComponent as exc:
                                raise RuntimeError(
                                    f"Unsafe manifest path for run {run_id}: paragraph subtitle path {raw_subtitle_path!r}"
                                ) from exc
                        ffmpeg.merge_subtitles(
                            merged_sub_inputs,
                            [duration_by_section[sid] for sid in ordered_sections],
                            merged_sub_path,
                        )
                        subtitle_path = Path(merged_sub_path)
            else:
                audio_path = Path(run_audio_path) if run_audio_path else None
                subtitle_path = Path(run_sub_path) if run_sub_path else None
                scene_durations = [profile_data["max_duration_seconds"] / scene_count] * scene_count
        else:
            audio_path = Path(run_audio_path) if run_audio_path else None
            subtitle_path = Path(run_sub_path) if run_sub_path else None
            scene_durations = [profile_data["max_duration_seconds"] / scene_count] * scene_count

        output_path = f"{_ARTIFACT_ROOT}/{run_id}/render/output.mp4"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            ffmpeg.render(
                RenderInput(
                    image_paths=image_paths,
                    audio_path=audio_path,
                    subtitle_path=subtitle_path,
                    scene_durations=scene_durations,
                ),
                Path(output_path),
            )
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
                workspace_id=ctx.workspace_id,
                project_id=ctx.project_id,
            )
        except Exception:
            logger.warning("Failed to record provider usage", exc_info=True)

        from creator_service.artifact_storage_integration import store_artifact_file

        uploaded = store_artifact_file(run_id, output_path, "video/mp4")
        artifact = await _render_service.create_artifact(
            run_id=run_id,
            path=output_path,
            render_profile=render_profile,
            storage_provider=uploaded.storage_provider,
            storage_key=uploaded.key,
        )

        return TaskResult(
            status="success",
            extra={
                "render_profile": render_profile,
                "video_artifact_id": artifact.id,
                "video_path": artifact.path,
                "scene_count": len(manifest["scenes"]),
                "audio_path": str(audio_path) if audio_path else None,
                "subtitle_path": str(subtitle_path) if subtitle_path else None,
            },
        )

    return run_task(self, run_id, config, execute)
