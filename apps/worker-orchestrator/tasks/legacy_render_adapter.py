from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from creator_domain.models import RenderPlan
from creator_service.ffmpeg_service import FFmpegService
from creator_service.recipe_profile import resolve_quality_profile
from creator_service.render_profile import TransitionStyle
from tasks.legacy_render_audio import prepare_audio
from tasks.legacy_render_contract import LegacyManifest, LegacyRequest, LegacyServices, build_render_plan, resolve_profile
from tasks.legacy_render_effects import climax_index, mix_effects, style_subtitles


@dataclass(frozen=True, slots=True)
class LegacyRenderInputs:
    plan: RenderPlan
    ffmpeg: FFmpegService
    audio: Path | None
    subtitles: Path | None
    scene_count: int


async def prepare_legacy_render(request: LegacyRequest, services: LegacyServices) -> LegacyRenderInputs:
    manifest = await LegacyManifest.load(request, services)
    if not manifest.scenes:
        raise RuntimeError("No scenes found for render")
    active_plan = await services.plans.get_active_plan(request.run_id)
    scenes = manifest.scenes
    if active_plan is not None:
        by_id = {scene.scene_id: scene for scene in scenes}
        ordered = [by_id[scene.scene_id] for scene in active_plan.scenes if scene.scene_id in by_id]
        ordered_ids = {scene.scene_id for scene in ordered}
        scenes = ordered + [scene for scene in scenes if scene.scene_id not in ordered_ids]
    paths = [request.path(scene.asset_path) for scene in scenes]
    profile = resolve_profile(request.profile_name)
    quality = resolve_quality_profile(request.profile_name)
    profile.transition_style = TransitionStyle(quality.transition)
    ffmpeg = services.ffmpeg_factory(profile)
    inputs = await prepare_audio(request, services, manifest, ffmpeg=ffmpeg)
    audio = mix_effects(request, inputs, active_plan)
    subtitles = await style_subtitles(request, services, inputs.subtitles, ffmpeg=ffmpeg)
    paced_paths: list[Path] = []
    paced_durations: list[float] = []
    for path, duration in zip(paths, inputs.durations, strict=True):
        if duration > quality.max_scene_duration:
            paced_paths.extend([path, path])
            paced_durations.extend([duration / 2, duration / 2])
        else:
            paced_paths.append(path)
            paced_durations.append(duration)
    transitions: list[str] | None = None
    if quality.hard_cut_on_climax and len(paced_paths) >= 4:
        transitions = [quality.transition] * len(paced_paths)
        transitions[climax_index(active_plan, len(paced_paths))] = "cut"
    plan = build_render_plan(paced_paths, paced_durations, transitions, profile)
    return LegacyRenderInputs(plan, ffmpeg, audio, subtitles, len(manifest.scenes))
