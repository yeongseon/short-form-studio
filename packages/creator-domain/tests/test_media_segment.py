from __future__ import annotations

import math

import pytest
from creator_domain.models import MediaSegment
from pydantic import ValidationError


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "segment-1",
        "scene_id": "scene-2",
        "asset_id": 42,
        "timeline_start_seconds": 0.0,
        "duration_seconds": 4.5,
    }
    payload.update(overrides)
    return payload


def test_media_segment_minimal_valid() -> None:
    seg = MediaSegment.model_validate(_payload())
    assert seg.id == "segment-1"
    assert seg.scene_id == "scene-2"
    assert seg.asset_id == 42
    assert seg.timeline_start_seconds == 0.0
    assert seg.duration_seconds == 4.5
    assert seg.trim_start_seconds is None
    assert seg.trim_end_seconds is None
    assert seg.fit_mode == "cover"
    assert seg.transition is None


def test_media_segment_full_payload() -> None:
    seg = MediaSegment.model_validate(
        _payload(
            timeline_start_seconds=10.0,
            duration_seconds=3.0,
            trim_start_seconds=1.5,
            trim_end_seconds=4.5,
            fit_mode="contain",
            transition="fade",
        )
    )
    assert seg.trim_start_seconds == 1.5
    assert seg.trim_end_seconds == 4.5
    assert seg.fit_mode == "contain"
    assert seg.transition == "fade"


def test_rejects_non_positive_duration() -> None:
    with pytest.raises(ValidationError):
        MediaSegment.model_validate(_payload(duration_seconds=0))
    with pytest.raises(ValidationError):
        MediaSegment.model_validate(_payload(duration_seconds=-1.0))


def test_rejects_non_finite_duration() -> None:
    with pytest.raises(ValidationError):
        MediaSegment.model_validate(_payload(duration_seconds=math.inf))
    with pytest.raises(ValidationError):
        MediaSegment.model_validate(_payload(duration_seconds=math.nan))


def test_rejects_negative_timeline_start() -> None:
    with pytest.raises(ValidationError):
        MediaSegment.model_validate(_payload(timeline_start_seconds=-0.1))


def test_rejects_negative_trims() -> None:
    with pytest.raises(ValidationError):
        MediaSegment.model_validate(_payload(trim_start_seconds=-1.0))
    with pytest.raises(ValidationError):
        MediaSegment.model_validate(_payload(trim_end_seconds=-1.0))


def test_rejects_trim_start_after_trim_end() -> None:
    with pytest.raises(ValidationError):
        MediaSegment.model_validate(
            _payload(trim_start_seconds=5.0, trim_end_seconds=2.0)
        )


def test_rejects_positive_asset_id_constraint() -> None:
    with pytest.raises(ValidationError):
        MediaSegment.model_validate(_payload(asset_id=0))


def test_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        MediaSegment.model_validate(_payload(unexpected="x"))


def test_no_short_only_duration_ceiling() -> None:
    # A generic segment must allow long durations; no 60s/3min core cap.
    seg = MediaSegment.model_validate(_payload(duration_seconds=1800.0))
    assert seg.duration_seconds == 1800.0


def test_multiple_segments_per_scene_allowed() -> None:
    # The model itself imposes no one-segment-per-scene rule.
    a = MediaSegment.model_validate(_payload(id="segment-1", scene_id="scene-1"))
    b = MediaSegment.model_validate(
        _payload(id="segment-2", scene_id="scene-1", timeline_start_seconds=4.5)
    )
    assert a.scene_id == b.scene_id
    assert a.id != b.id


def test_round_trips_via_json() -> None:
    seg = MediaSegment.model_validate(
        _payload(trim_start_seconds=1.0, trim_end_seconds=3.0, transition="cut")
    )
    restored = MediaSegment.model_validate_json(seg.to_json())
    assert restored == seg
