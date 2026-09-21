from __future__ import annotations

import pytest
from creator_domain.models import (
    EncodingProfile,
    OutputSpec,
    RenderPlan,
    RenderSegment,
    RenderSegmentKind,
)
from pydantic import ValidationError


def _segment(**overrides: object) -> RenderSegment:
    payload: dict[str, object] = {
        "kind": RenderSegmentKind.IMAGE,
        "source": "data/artifacts/1/visual/scene-1.png",
        "timeline_start_seconds": 0.0,
        "duration_seconds": 4.0,
    }
    payload.update(overrides)
    return RenderSegment.model_validate(payload)


def _plan_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "segments": [_segment()],
        "output_spec": OutputSpec.short_vertical(),
        "encoding_profile": EncodingProfile.standard(),
    }
    payload.update(overrides)
    return payload


def test_render_plan_minimal_valid() -> None:
    plan = RenderPlan.model_validate(_plan_payload())
    assert len(plan.segments) == 1
    assert plan.output_spec.width == 1080
    assert plan.encoding_profile.name == "standard"
    assert plan.narration_path is None
    assert plan.subtitle_path is None
    assert plan.music_path is None


def test_render_plan_with_optional_layers() -> None:
    plan = RenderPlan.model_validate(
        _plan_payload(
            narration_path="data/artifacts/1/audio/narration.wav",
            subtitle_path="data/artifacts/1/subtitles/subs.srt",
            music_path="data/artifacts/1/audio/bgm.mp3",
        )
    )
    assert plan.narration_path == "data/artifacts/1/audio/narration.wav"
    assert plan.subtitle_path == "data/artifacts/1/subtitles/subs.srt"
    assert plan.music_path == "data/artifacts/1/audio/bgm.mp3"


def test_render_plan_requires_at_least_one_segment() -> None:
    with pytest.raises(ValidationError):
        RenderPlan.model_validate(_plan_payload(segments=[]))


def test_render_plan_preserves_multiple_segments_order() -> None:
    plan = RenderPlan.model_validate(
        _plan_payload(
            segments=[
                _segment(source="a.png", timeline_start_seconds=0.0, duration_seconds=3.0),
                _segment(source="b.png", timeline_start_seconds=3.0, duration_seconds=2.0),
            ]
        )
    )
    assert [s.source for s in plan.segments] == ["a.png", "b.png"]


def test_render_plan_rejects_overlapping_segments() -> None:
    # Segments must not overlap on the timeline (precise timing).
    with pytest.raises(ValidationError):
        RenderPlan.model_validate(
            _plan_payload(
                segments=[
                    _segment(source="a.png", timeline_start_seconds=0.0, duration_seconds=5.0),
                    _segment(source="b.png", timeline_start_seconds=3.0, duration_seconds=2.0),
                ]
            )
        )


def test_render_plan_rejects_absolute_paths() -> None:
    # Paths must be authorized compiler/service outputs, not arbitrary absolute
    # client filesystem paths.
    with pytest.raises(ValidationError):
        RenderPlan.model_validate(_plan_payload(narration_path="/etc/passwd"))


def test_render_plan_rejects_traversal_paths() -> None:
    with pytest.raises(ValidationError):
        RenderPlan.model_validate(_plan_payload(subtitle_path="../../secret.srt"))


def test_render_plan_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        RenderPlan.model_validate(_plan_payload(unexpected="x"))


def test_render_plan_has_no_product_classification_fields() -> None:
    # No short/long product labels or duration ceilings in the render contract.
    fields = set(RenderPlan.model_fields)
    assert "content_format" not in fields
    assert "is_short" not in fields
    assert "max_duration_seconds" not in fields


def test_render_plan_total_duration() -> None:
    plan = RenderPlan.model_validate(
        _plan_payload(
            segments=[
                _segment(source="a.png", timeline_start_seconds=0.0, duration_seconds=3.0),
                _segment(source="b.png", timeline_start_seconds=3.0, duration_seconds=2.5),
            ]
        )
    )
    assert plan.total_duration_seconds == pytest.approx(5.5)


def test_render_plan_allows_long_total_duration() -> None:
    plan = RenderPlan.model_validate(
        _plan_payload(
            segments=[_segment(duration_seconds=1800.0)],
        )
    )
    assert plan.total_duration_seconds == pytest.approx(1800.0)


def test_render_plan_round_trips_via_json() -> None:
    plan = RenderPlan.model_validate(
        _plan_payload(narration_path="data/artifacts/1/audio/n.wav")
    )
    restored = RenderPlan.model_validate_json(plan.to_json())
    assert restored == plan
