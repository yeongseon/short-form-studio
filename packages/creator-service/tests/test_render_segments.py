"""SF-21: characterize the legacy image_paths RenderInput and pin the new
segment-driven adapter that builds it, without changing render() internals.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from creator_domain.models import RenderPlan, RenderSegment, RenderSegmentKind
from creator_service.ffmpeg_service import RenderInput
from creator_service.render_segments import (
    UnsupportedSegmentKindError,
    render_input_from_plan,
    render_input_from_segments,
)


def _img(source: str, start: float, dur: float, **overrides: object) -> RenderSegment:
    payload: dict[str, object] = {
        "kind": RenderSegmentKind.IMAGE,
        "source": source,
        "timeline_start_seconds": start,
        "duration_seconds": dur,
    }
    payload.update(overrides)
    return RenderSegment.model_validate(payload)


def test_adapter_builds_render_input_preserving_order_and_durations() -> None:
    segments = [
        _img("data/artifacts/1/visual/scene-1.png", 0.0, 3.0),
        _img("data/artifacts/1/visual/scene-2.png", 3.0, 2.5),
    ]

    result = render_input_from_segments(segments)

    assert isinstance(result, RenderInput)
    assert result.image_paths == [
        Path("data/artifacts/1/visual/scene-1.png"),
        Path("data/artifacts/1/visual/scene-2.png"),
    ]
    assert result.scene_durations == [3.0, 2.5]


def test_adapter_orders_by_timeline_start() -> None:
    segments = [
        _img("b.png", 3.0, 2.0),
        _img("a.png", 0.0, 3.0),
    ]
    result = render_input_from_segments(segments)
    assert result.image_paths == [Path("a.png"), Path("b.png")]
    assert result.scene_durations == [3.0, 2.0]


def test_adapter_carries_audio_and_subtitle_paths() -> None:
    result = render_input_from_segments(
        [_img("a.png", 0.0, 3.0)],
        audio_path=Path("data/artifacts/1/audio/n.wav"),
        subtitle_path=Path("data/artifacts/1/subtitles/s.srt"),
    )
    assert result.audio_path == Path("data/artifacts/1/audio/n.wav")
    assert result.subtitle_path == Path("data/artifacts/1/subtitles/s.srt")


def test_adapter_collects_per_scene_transitions() -> None:
    segments = [
        _img("a.png", 0.0, 3.0, transition="fade"),
        _img("b.png", 3.0, 2.0, transition="cut"),
    ]
    result = render_input_from_segments(segments)
    assert result.scene_transitions == ["fade", "cut"]


def test_adapter_transitions_none_when_no_segment_has_one() -> None:
    result = render_input_from_segments([_img("a.png", 0.0, 3.0)])
    assert result.scene_transitions is None


def test_adapter_rejects_empty_segments() -> None:
    with pytest.raises(ValueError):
        render_input_from_segments([])


def test_adapter_rejects_video_kind_for_legacy_image_path() -> None:
    # The legacy image_paths renderer only handles images; a video segment must
    # be rejected explicitly rather than silently mis-rendered.
    video = RenderSegment.model_validate(
        {
            "kind": RenderSegmentKind.VIDEO,
            "source": "clip.mp4",
            "timeline_start_seconds": 0.0,
            "duration_seconds": 3.0,
        }
    )
    with pytest.raises(UnsupportedSegmentKindError):
        render_input_from_segments([video])


def test_render_input_from_plan_uses_plan_layers() -> None:
    from creator_domain.models import EncodingProfile, OutputSpec

    plan = RenderPlan.model_validate(
        {
            "segments": [_img("a.png", 0.0, 3.0), _img("b.png", 3.0, 2.0)],
            "output_spec": OutputSpec.short_vertical(),
            "encoding_profile": EncodingProfile.standard(),
            "narration_path": "data/artifacts/1/audio/n.wav",
            "subtitle_path": "data/artifacts/1/subtitles/s.srt",
        }
    )

    result = render_input_from_plan(plan)

    assert result.image_paths == [Path("a.png"), Path("b.png")]
    assert result.scene_durations == [3.0, 2.0]
    assert result.audio_path == Path("data/artifacts/1/audio/n.wav")
    assert result.subtitle_path == Path("data/artifacts/1/subtitles/s.srt")
