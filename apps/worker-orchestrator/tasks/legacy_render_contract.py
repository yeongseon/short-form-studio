from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from creator_domain.models import EncodingProfile, OutputSpec, RenderPlan, RenderSegment, RenderSegmentKind
from creator_domain.sanitize import UnsafePathComponent, validate_artifact_path
from creator_service.audio_service import AudioService
from creator_service.ffmpeg_service import FFmpegService
from creator_service.render_profile import RenderProfile
from creator_service.render_service import RenderService
from creator_service.script_service import ScriptService
from creator_service.subtitle_service import SubtitleService
from creator_service.visual_asset_service import VisualAssetService
from creator_service.visual_plan_service import VisualPlanService
from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LegacyServices:
    render: RenderService
    visuals: VisualAssetService
    audio: AudioService
    subtitles: SubtitleService
    plans: VisualPlanService
    scripts: ScriptService
    ffmpeg_factory: Callable[[RenderProfile], FFmpegService]


@dataclass(frozen=True, slots=True)
class LegacyRequest:
    run_id: int
    profile_name: str
    artifact_root: str

    def path(self, raw: str) -> Path:
        try:
            validate_artifact_path(raw, self.artifact_root)
        except UnsafePathComponent as exc:
            raise RuntimeError(f"Unsafe manifest path for run {self.run_id}") from exc
        return Path(raw)

    def output(self, name: str) -> Path:
        path = self.path(f"{self.artifact_root}/{self.run_id}/render/{name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class ManifestProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    name: str = "shorts_default"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    transition_style: str = "fade"
    min_duration_seconds: float = 15
    max_duration_seconds: float
    crf: int = 18
    preset: str = "fast"
    burn_subtitles: bool = True
    subtitle_font_size: int = 48
    resolution: str | None = None
    codec: str | None = None
    bitrate: str | None = None


class ManifestScene(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    scene_id: str
    asset_path: str


class LegacyManifest(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    scenes: list[ManifestScene]
    audio_path: str | None
    subtitle_path: str | None
    render_profile: ManifestProfile

    @classmethod
    async def load(cls, request: LegacyRequest, services: LegacyServices) -> LegacyManifest:
        raw = await services.render.build_render_manifest(
            request.run_id, services.visuals, services.audio, services.subtitles,
            render_profile_name=request.profile_name,
        )
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            raise RuntimeError("Invalid render_profile or render manifest") from exc


def resolve_profile(name: str) -> RenderProfile:
    registry = {
        "shorts_default": RenderProfile.default,
        "high_quality": RenderProfile.high_quality,
        "fast_preview": RenderProfile.fast_preview,
    }
    factory = registry.get(name)
    if factory is None:
        logger.warning("Unknown render profile %r, falling back to default", name)
        return RenderProfile.default()
    return factory()


def build_render_plan(
    image_paths: list[Path], scene_durations: list[float],
    scene_transitions: list[str] | None, profile: RenderProfile,
) -> RenderPlan:
    if len(image_paths) != len(scene_durations):
        raise ValueError("image_paths and scene_durations must have equal length")
    segments: list[RenderSegment] = []
    cursor = 0.0
    for index, (image, duration) in enumerate(zip(image_paths, scene_durations, strict=True)):
        transition = (
            scene_transitions[index]
            if scene_transitions is not None and index < len(scene_transitions) else None
        )
        segments.append(RenderSegment(
            kind=RenderSegmentKind.IMAGE, source=str(image),
            timeline_start_seconds=cursor, duration_seconds=duration,
            transition=transition or None,
        ))
        cursor += duration
    return RenderPlan(
        segments=segments, output_spec=OutputSpec.from_render_profile(profile),
        encoding_profile=EncodingProfile.from_render_profile(profile),
    )
