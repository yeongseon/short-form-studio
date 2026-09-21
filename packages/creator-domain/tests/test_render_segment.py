from __future__ import annotations

import math

import pytest
from creator_domain.models import RenderSegment, RenderSegmentKind
from pydantic import ValidationError


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": RenderSegmentKind.IMAGE,
        "source": "data/artifacts/1/visual/scene-1.png",
        "timeline_start_seconds": 0.0,
        "duration_seconds": 4.0,
    }
    payload.update(overrides)
    return payload


def test_render_segment_kind_members() -> None:
    assert {k.value for k in RenderSegmentKind} == {"image", "video"}


def test_image_render_segment_minimal() -> None:
    seg = RenderSegment.model_validate(_payload())
    assert seg.kind is RenderSegmentKind.IMAGE
    assert seg.source == "data/artifacts/1/visual/scene-1.png"
    assert seg.timeline_start_seconds == 0.0
    assert seg.duration_seconds == 4.0
    assert seg.trim_start_seconds is None
    assert seg.trim_end_seconds is None
    assert seg.fit_mode == "cover"
    assert seg.transition is None


def test_video_render_segment_with_trims() -> None:
    seg = RenderSegment.model_validate(
        _payload(
            kind="video",
            source="data/artifacts/1/video/clip.mp4",
            timeline_start_seconds=4.0,
            duration_seconds=3.0,
            trim_start_seconds=1.0,
            trim_end_seconds=4.0,
            fit_mode="contain",
            transition="fade",
        )
    )
    assert seg.kind is RenderSegmentKind.VIDEO
    assert seg.trim_start_seconds == 1.0
    assert seg.trim_end_seconds == 4.0
    assert seg.fit_mode == "contain"
    assert seg.transition == "fade"


def test_kind_coerces_from_string() -> None:
    assert RenderSegment.model_validate(_payload(kind="video")).kind is RenderSegmentKind.VIDEO


def test_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        RenderSegment.model_validate(_payload(kind="audio"))


def test_rejects_empty_source() -> None:
    with pytest.raises(ValidationError):
        RenderSegment.model_validate(_payload(source=""))


def test_rejects_non_positive_duration() -> None:
    with pytest.raises(ValidationError):
        RenderSegment.model_validate(_payload(duration_seconds=0))
    with pytest.raises(ValidationError):
        RenderSegment.model_validate(_payload(duration_seconds=-2.0))


def test_rejects_non_finite_times() -> None:
    with pytest.raises(ValidationError):
        RenderSegment.model_validate(_payload(duration_seconds=math.inf))
    with pytest.raises(ValidationError):
        RenderSegment.model_validate(_payload(timeline_start_seconds=math.nan))


def test_rejects_negative_timeline_start() -> None:
    with pytest.raises(ValidationError):
        RenderSegment.model_validate(_payload(timeline_start_seconds=-1.0))


def test_rejects_trim_start_after_end() -> None:
    with pytest.raises(ValidationError):
        RenderSegment.model_validate(
            _payload(kind="video", trim_start_seconds=5.0, trim_end_seconds=2.0)
        )


def test_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        RenderSegment.model_validate(_payload(unexpected="x"))


def test_deterministic_serialization() -> None:
    seg = RenderSegment.model_validate(_payload(transition="cut"))
    assert RenderSegment.model_validate_json(seg.to_json()) == seg
    # Two equal segments serialize identically.
    other = RenderSegment.model_validate(_payload(transition="cut"))
    assert seg.to_json() == other.to_json()


def test_no_short_only_duration_ceiling() -> None:
    seg = RenderSegment.model_validate(_payload(duration_seconds=1800.0))
    assert seg.duration_seconds == 1800.0
