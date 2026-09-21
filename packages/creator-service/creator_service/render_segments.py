"""SF-21: segment-driven renderer entry point + legacy image_paths adapter.

Builds the existing ``RenderInput`` (parallel image_paths / scene_durations /
scene_transitions lists) from ordered RenderSegments or a RenderPlan, so callers
can move toward segments without changing ``FFmpegService.render`` internals.
"""

from __future__ import annotations

from pathlib import Path

from creator_domain.models import RenderPlan, RenderSegment, RenderSegmentKind

from creator_service.ffmpeg_service import RenderInput
from creator_service.render_profile import AudioCodec, Codec, RenderProfile


class UnsupportedSegmentKindError(ValueError):
    """Raised when a segment kind is not supported by the legacy image path."""


def render_input_from_segments(
    segments: list[RenderSegment],
    *,
    audio_path: Path | None = None,
    subtitle_path: Path | None = None,
) -> RenderInput:
    """Adapt ordered image RenderSegments into a legacy RenderInput.

    Segments are ordered by ``timeline_start_seconds``. Only image segments are
    supported by this legacy (image_paths) path; a video segment is rejected
    explicitly rather than silently mis-rendered.
    """
    if not segments:
        raise ValueError("segments must not be empty")

    ordered = sorted(segments, key=lambda s: s.timeline_start_seconds)
    for seg in ordered:
        if seg.kind is not RenderSegmentKind.IMAGE:
            raise UnsupportedSegmentKindError(
                f"legacy image renderer does not support segment kind {seg.kind.value!r}"
            )

    image_paths = [Path(seg.source) for seg in ordered]
    scene_durations = [seg.duration_seconds for seg in ordered]

    transitions = [seg.transition for seg in ordered]
    scene_transitions = (
        [t if t is not None else "" for t in transitions]
        if any(t is not None for t in transitions)
        else None
    )

    return RenderInput(
        image_paths=image_paths,
        audio_path=audio_path,
        subtitle_path=subtitle_path,
        scene_durations=scene_durations,
        scene_transitions=scene_transitions,
    )


def render_input_from_plan(plan: RenderPlan) -> RenderInput:
    """Adapt a RenderPlan's segments and compiled layers into a RenderInput."""
    return render_input_from_segments(
        plan.segments,
        audio_path=Path(plan.narration_path) if plan.narration_path else None,
        subtitle_path=Path(plan.subtitle_path) if plan.subtitle_path else None,
    )


def render_profile_from_plan(plan: RenderPlan) -> RenderProfile:
    """Map a RenderPlan's OutputSpec geometry and EncodingProfile into a RenderProfile.

    Bridges the generic domain value objects onto the FFmpegService-facing
    RenderProfile: OutputSpec drives width/height/fps, EncodingProfile drives
    codec/crf/preset. The domain codec values (e.g. "libx264"/"aac") match the
    RenderProfile Codec/AudioCodec enum values, so they map by value.
    """
    spec = plan.output_spec
    encoding = plan.encoding_profile
    return RenderProfile(
        name=encoding.name,
        width=spec.width,
        height=spec.height,
        fps=spec.fps,
        video_codec=Codec(encoding.video_codec.value),
        audio_codec=AudioCodec(encoding.audio_codec.value),
        crf=encoding.crf,
        preset=encoding.preset,
    )
