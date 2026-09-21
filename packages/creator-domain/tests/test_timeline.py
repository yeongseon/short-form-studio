"""SF-26: Timeline domain model — one per Project, stable identity + revision,
generic time-based content grouped as scene→segments, no Sequence domain and no
short-only duration ceiling. Valid/invalid timings + deterministic serialization.
"""

from __future__ import annotations

import pytest
from creator_domain.models import MediaSegment, Timeline
from pydantic import ValidationError


def _segment(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "segment-1",
        "scene_id": "scene-1",
        "asset_id": 1,
        "timeline_start_seconds": 0.0,
        "duration_seconds": 4.0,
    }
    payload.update(overrides)
    return payload


def _timeline(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "timeline-1",
        "project_id": 7,
        "revision": 1,
        "segments": [_segment()],
    }
    payload.update(overrides)
    return payload


def test_timeline_minimal_valid() -> None:
    tl = Timeline.model_validate(_timeline())
    assert tl.id == "timeline-1"
    assert tl.project_id == 7
    assert tl.revision == 1
    assert len(tl.segments) == 1
    assert isinstance(tl.segments[0], MediaSegment)


def test_timeline_requires_positive_project_id() -> None:
    with pytest.raises(ValidationError):
        Timeline.model_validate(_timeline(project_id=0))


def test_timeline_requires_nonempty_id() -> None:
    with pytest.raises(ValidationError):
        Timeline.model_validate(_timeline(id=""))


def test_timeline_revision_starts_at_zero_allowed() -> None:
    tl = Timeline.model_validate(_timeline(revision=0))
    assert tl.revision == 0


def test_timeline_rejects_negative_revision() -> None:
    with pytest.raises(ValidationError):
        Timeline.model_validate(_timeline(revision=-1))


def test_timeline_allows_empty_segments() -> None:
    tl = Timeline.model_validate(_timeline(segments=[]))
    assert tl.segments == []
    assert tl.total_duration_seconds == 0.0


def test_timeline_groups_multiple_segments_per_scene() -> None:
    tl = Timeline.model_validate(
        _timeline(
            segments=[
                _segment(id="s1", scene_id="scene-1", timeline_start_seconds=0.0, duration_seconds=3.0),
                _segment(id="s2", scene_id="scene-1", timeline_start_seconds=3.0, duration_seconds=2.0),
                _segment(id="s3", scene_id="scene-2", timeline_start_seconds=5.0, duration_seconds=4.0),
            ]
        )
    )
    grouped = tl.segments_by_scene()
    assert list(grouped.keys()) == ["scene-1", "scene-2"]
    assert [s.id for s in grouped["scene-1"]] == ["s1", "s2"]
    assert [s.id for s in grouped["scene-2"]] == ["s3"]


def test_timeline_total_duration_no_cap() -> None:
    # No short-only ceiling: a multi-hour timeline is valid.
    tl = Timeline.model_validate(
        _timeline(
            segments=[
                _segment(id="s1", timeline_start_seconds=0.0, duration_seconds=3600.0),
                _segment(id="s2", timeline_start_seconds=3600.0, duration_seconds=3600.0),
            ]
        )
    )
    assert tl.total_duration_seconds == 7200.0


def test_timeline_rejects_overlapping_segments() -> None:
    with pytest.raises(ValidationError):
        Timeline.model_validate(
            _timeline(
                segments=[
                    _segment(id="s1", timeline_start_seconds=0.0, duration_seconds=5.0),
                    _segment(id="s2", timeline_start_seconds=3.0, duration_seconds=2.0),
                ]
            )
        )


def test_timeline_rejects_duplicate_segment_ids() -> None:
    with pytest.raises(ValidationError):
        Timeline.model_validate(
            _timeline(
                segments=[
                    _segment(id="dup", timeline_start_seconds=0.0, duration_seconds=2.0),
                    _segment(id="dup", timeline_start_seconds=2.0, duration_seconds=2.0),
                ]
            )
        )


def test_timeline_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Timeline.model_validate(_timeline(unexpected="x"))


def test_timeline_deterministic_serialization() -> None:
    payload = _timeline(
        segments=[
            _segment(id="s1", timeline_start_seconds=0.0, duration_seconds=3.0),
            _segment(id="s2", timeline_start_seconds=3.0, duration_seconds=2.0),
        ]
    )
    first = Timeline.model_validate(payload).to_json()
    second = Timeline.model_validate(payload).to_json()
    assert first == second
    assert Timeline.from_dict(payload).to_json() == first
