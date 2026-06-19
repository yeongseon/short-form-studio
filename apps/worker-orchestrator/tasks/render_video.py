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
from creator_service.script_service import script_service as _script_service
from creator_service.subtitle_service import subtitle_service as _subtitle_service
from creator_service.telemetry import trace_task
from creator_service.usage_service import record_provider_call
from creator_service.visual_asset_service import visual_asset_service as _visual_asset_service
from creator_service.visual_plan_service import visual_plan_service as _visual_plan_service
from tasks.task_runner import TaskContext, TaskResult, TaskRunnerConfig, run_task

logger = logging.getLogger(__name__)
_ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")


def compute_scene_durations(
    ffmpeg: FFmpegService,
    audio_path: Path | None,
    scene_count: int,
    max_duration_seconds: float,
) -> list[float]:
    """Compute per-scene durations from audio length or max_duration fallback.

    Production logic extracted for testability.
    """
    if audio_path:
        try:
            total_dur = ffmpeg.get_audio_duration(str(audio_path))
        except Exception:
            total_dur = max_duration_seconds
        return [total_dur / scene_count] * scene_count
    return [max_duration_seconds / scene_count] * scene_count

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
        # Resolve render profile and apply quality profile overrides
        resolved_profile = _resolve_profile(render_profile)
        try:
            from creator_service.quality_profile import get_quality_profile
            from creator_service.render_profile import TransitionStyle
            _qp = get_quality_profile(render_profile if render_profile != "shorts_default" else "ssul_v2")
            # Override transition style from quality profile
            transition_map = {
                "ken_burns": TransitionStyle.KEN_BURNS,
                "ken_burns_lite": TransitionStyle.KEN_BURNS_LITE,
                "fade": TransitionStyle.FADE,
                "cut": TransitionStyle.CUT,
            }
            if _qp.transition in transition_map:
                resolved_profile.transition_style = transition_map[_qp.transition]
        except Exception:
            pass
        ffmpeg = FFmpegService(profile=resolved_profile)
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
                scene_durations = compute_scene_durations(
                    ffmpeg, audio_path, scene_count, profile_data["max_duration_seconds"]
                )
        else:
            audio_path = Path(run_audio_path) if run_audio_path else None
            subtitle_path = Path(run_sub_path) if run_sub_path else None
            scene_durations = compute_scene_durations(
                ffmpeg, audio_path, scene_count, profile_data["max_duration_seconds"]
            )

        # --- BGM: generate ambient background music and mix with narration ---
        if audio_path:
            try:
                from creator_service.bgm_service import bgm_service
                from creator_service.quality_profile import get_quality_profile
                qp = get_quality_profile(render_profile if render_profile != "shorts_default" else "ssul_v2")
                total_duration = sum(scene_durations)
                bgm_path = f"{_ARTIFACT_ROOT}/{run_id}/render/bgm.mp3"
                Path(bgm_path).parent.mkdir(parents=True, exist_ok=True)
                bgm_service.generate_ambient_bgm(total_duration, bgm_path, mood=qp.bgm_mood)
                mixed_path = f"{_ARTIFACT_ROOT}/{run_id}/render/audio_mixed.mp3"
                bgm_service.mix_audio_with_bgm(str(audio_path), bgm_path, mixed_path, bgm_volume=qp.bgm_volume)
                audio_path = Path(mixed_path)
                logger.info("BGM mixed for run %d (mood=%s, vol=%.2f)", run_id, qp.bgm_mood, qp.bgm_volume)

                # --- SFX: overlay sound effects at scene transitions ---
                if qp.sfx_enabled:
                    try:
                        cumulative = 0.0
                        sfx_timestamps: list[tuple[float, str]] = []
                        for i, dur in enumerate(scene_durations):
                            if i == 0:
                                # Hook scene — use hook SFX at start
                                sfx_timestamps.append((0.3, qp.sfx_hook_type))
                            elif i == len(scene_durations) - 1:
                                # Last scene — no transition SFX
                                pass
                            else:
                                # Transition SFX at scene boundary
                                sfx_timestamps.append((cumulative - 0.1, qp.sfx_transition_type))
                            # Detect climax by scene metadata, fallback to index heuristic
                            sfx_climax_idx = min(3, len(scene_durations) - 2)
                            if active_plan is not None:
                                for pi, ps in enumerate(active_plan.scenes):
                                    if ps.section_type.lower() in ("climax", "body3"):
                                        if pi < len(scene_durations):
                                            sfx_climax_idx = pi
                                        break
                            if i == sfx_climax_idx and len(scene_durations) >= 4:
                                sfx_timestamps.append((cumulative + dur * 0.5, qp.sfx_climax_type))
                            cumulative += dur
                        sfx_output = f"{_ARTIFACT_ROOT}/{run_id}/render/audio_sfx.mp3"
                        result_path = bgm_service.mix_sfx_at_timestamps(
                            str(audio_path), sfx_timestamps, sfx_output, sfx_volume=qp.sfx_volume
                        )
                        audio_path = Path(result_path)
                        logger.info("SFX mixed for run %d (%d effects)", run_id, len(sfx_timestamps))
                    except Exception as sfx_exc:
                        logger.warning("SFX mixing failed for run %d: %s", run_id, sfx_exc)
                # --- Loudness normalization (final audio processing step) ---
                if qp.loudnorm_enabled:
                    try:
                        norm_path = f"{_ARTIFACT_ROOT}/{run_id}/render/audio_normalized.mp3"
                        normalized = bgm_service.normalize_loudness(
                            str(audio_path), norm_path,
                            target_lufs=qp.loudnorm_target_lufs,
                            true_peak=qp.loudnorm_true_peak,
                        )
                        audio_path = Path(normalized)
                        logger.info("Audio normalized to %.1f LUFS for run %d", qp.loudnorm_target_lufs, run_id)
                    except Exception as norm_exc:
                        logger.warning("Loudness normalization failed for run %d: %s", run_id, norm_exc)
            except Exception as exc:
                logger.warning("BGM mixing failed for run %d, using original audio: %s", run_id, exc)
        # --- Convert SRT to ASS for styled subtitles with keyword emphasis ---
        if subtitle_path and str(subtitle_path).endswith(".srt"):
            try:
                from tasks.script_qc import extract_emphasis_words
                from creator_service.quality_profile import get_quality_profile
                qp = get_quality_profile(render_profile if render_profile != "shorts_default" else "ssul_v2")
                # Extract emphasis words from script if available
                emphasis_words: list[str] | None = None
                if qp.subtitle_emphasis:
                    draft = await _script_service.get_active_draft(run_id)
                    if draft and draft.markdown_content:
                        emphasis_words = extract_emphasis_words(draft.markdown_content)
                ass_path = str(subtitle_path).replace(".srt", ".ass")
                ffmpeg.convert_srt_to_ass(
                    str(subtitle_path), ass_path,
                    emphasis_words=emphasis_words,
                    emphasis_color=qp.emphasis_color,
                )
                subtitle_path = Path(ass_path)
                logger.info("Converted subtitles to ASS for run %d (emphasis_words=%d)", run_id, len(emphasis_words or []))
            except Exception as exc:
                logger.warning("ASS conversion failed for run %d, using SRT: %s", run_id, exc)

        output_path = f"{_ARTIFACT_ROOT}/{run_id}/render/output.mp4"
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # --- Pacing enforcement: split scenes > max_scene_duration into sub-beats ---
        try:
            from creator_service.quality_profile import get_quality_profile
            _qp_pace = get_quality_profile(render_profile if render_profile != "shorts_default" else "ssul_v2")
            max_scene_dur = _qp_pace.max_scene_duration
            new_image_paths: list[Path] = []
            new_scene_durations: list[float] = []
            for img, dur in zip(image_paths, scene_durations):
                if dur > max_scene_dur:
                    # Split into 2 sub-beats using same image
                    half = dur / 2.0
                    new_image_paths.extend([img, img])
                    new_scene_durations.extend([half, half])
                else:
                    new_image_paths.append(img)
                    new_scene_durations.append(dur)
            if len(new_image_paths) != len(image_paths):
                logger.info(
                    "Pacing: split %d scenes into %d sub-beats for run %d",
                    len(image_paths), len(new_image_paths), run_id,
                )
                image_paths = new_image_paths
                scene_durations = new_scene_durations
                scene_count = len(image_paths)
        except Exception:
            pass

        logger.debug(
            "Render inputs for run %d: images=%d audio=%s subs=%s durations=%s",
            run_id, len(image_paths), audio_path, subtitle_path, scene_durations,
        )
        # --- Compute per-scene transition overrides (hard cut on climax) ---
        scene_transitions: list[str] | None = None
        try:
            from creator_service.quality_profile import get_quality_profile
            _qp_trans = get_quality_profile(render_profile if render_profile != "shorts_default" else "ssul_v2")
            if _qp_trans.hard_cut_on_climax and scene_count >= 4:
                # Determine climax scene by metadata (section_type) if available,
                # falling back to index-based heuristic for legacy scripts.
                climax_idx = min(3, scene_count - 2)  # fallback: penultimate scene
                if active_plan is not None:
                    for idx, plan_scene in enumerate(active_plan.scenes):
                        if plan_scene.section_type.lower() in ("climax", "body3"):
                            if idx < scene_count:
                                climax_idx = idx
                            break
                scene_transitions = [_qp_trans.transition] * scene_count
                scene_transitions[climax_idx] = "cut"  # hard cut on climax
                logger.info("Hard cut on climax scene %d for run %d", climax_idx, run_id)
        except Exception:
            pass

        try:
            ffmpeg.render(
                RenderInput(
                    image_paths=image_paths,
                    audio_path=audio_path,
                    subtitle_path=subtitle_path,
                    scene_durations=scene_durations,
                    scene_transitions=scene_transitions,
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
            logger.error("FFmpeg render exception for run %d: %s: %s", run_id, type(exc).__name__, exc)
            message = str(exc).lower()
            if "429" in message or "rate limit" in message:
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
                idempotency_key=ctx.task_id,
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
            idempotency_key=ctx.task_id,
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
