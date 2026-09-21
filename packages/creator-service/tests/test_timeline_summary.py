"""SF-54: bounded, secret-free Timeline summary for LLM editing.

build_timeline_summary produces a deterministic, bounded summary of a saved
Timeline revision for an LLM editor: stable scene/segment ids, timings,
authorized asset facts (kind/duration only — never storage keys or credentials),
and the base revision. The summary is a pure function of the timeline + supplied
asset refs, so the same inputs yield byte-identical output.
"""

from __future__ import annotations

import json

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import Timeline
from creator_service.timeline_summary import (
    AssetSummaryRef,
    build_timeline_summary,
)


def _timeline() -> Timeline:
    return Timeline.model_validate(
        {
            "id": "tl-1",
            "project_id": 1,
            "revision": 7,
            "segments": [
                {
                    "id": "s2",
                    "scene_id": "scene-2",
                    "asset_id": 11,
                    "timeline_start_seconds": 4.0,
                    "duration_seconds": 3.0,
                    "transition": "fade",
                },
                {
                    "id": "s1",
                    "scene_id": "scene-1",
                    "asset_id": 10,
                    "timeline_start_seconds": 0.0,
                    "duration_seconds": 4.0,
                    "trim_start_seconds": 1.0,
                    "trim_end_seconds": 5.0,
                    "fit_mode": "contain",
                },
            ],
        }
    )


def _refs() -> dict[int, AssetSummaryRef]:
    return {
        10: AssetSummaryRef(id=10, media_type="VIDEO", duration_seconds=30.0),
        11: AssetSummaryRef(id=11, media_type="IMAGE", duration_seconds=None),
    }


def test_summary_is_associated_to_the_base_revision() -> None:
    summary = build_timeline_summary(_timeline(), asset_refs=_refs())
    assert summary["timeline_id"] == "tl-1"
    assert summary["project_id"] == 1
    assert summary["base_revision"] == 7


def test_summary_lists_segments_in_timeline_order() -> None:
    summary = build_timeline_summary(_timeline(), asset_refs=_refs())
    ids = [seg["id"] for seg in summary["segments"]]
    assert ids == ["s1", "s2"]


def test_summary_includes_stable_ids_timings_and_transitions() -> None:
    summary = build_timeline_summary(_timeline(), asset_refs=_refs())
    s1 = summary["segments"][0]
    assert s1["id"] == "s1"
    assert s1["scene_id"] == "scene-1"
    assert s1["timeline_start_seconds"] == 0.0
    assert s1["duration_seconds"] == 4.0
    assert s1["trim_start_seconds"] == 1.0
    assert s1["trim_end_seconds"] == 5.0
    assert s1["fit_mode"] == "contain"
    s2 = summary["segments"][1]
    assert s2["transition"] == "fade"


def test_summary_includes_authorized_asset_kind_and_duration() -> None:
    summary = build_timeline_summary(_timeline(), asset_refs=_refs())
    s1 = summary["segments"][0]
    assert s1["asset"]["id"] == 10
    assert s1["asset"]["media_type"] == "VIDEO"
    assert s1["asset"]["duration_seconds"] == 30.0


def test_summary_never_includes_storage_keys_or_secrets() -> None:
    summary = build_timeline_summary(_timeline(), asset_refs=_refs())
    blob = json.dumps(summary).lower()
    for forbidden in ("storage_key", "credential", "secret", "password", "token", "workspaces/"):
        assert forbidden not in blob


def test_summary_reports_total_duration_and_scene_grouping() -> None:
    summary = build_timeline_summary(_timeline(), asset_refs=_refs())
    assert summary["total_duration_seconds"] == 7.0
    assert summary["scenes"] == ["scene-1", "scene-2"]


def test_summary_is_deterministic() -> None:
    a = build_timeline_summary(_timeline(), asset_refs=_refs())
    b = build_timeline_summary(_timeline(), asset_refs=_refs())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_summary_rejects_a_segment_with_an_unresolved_asset() -> None:
    refs = {10: AssetSummaryRef(id=10, media_type="VIDEO", duration_seconds=30.0)}
    with pytest.raises(ValidationError):
        build_timeline_summary(_timeline(), asset_refs=refs)


def test_summary_rejects_max_segments_above_the_hard_cap() -> None:
    with pytest.raises(ValidationError):
        build_timeline_summary(_timeline(), asset_refs=_refs(), max_segments=501)


def test_summary_rejects_non_positive_max_segments() -> None:
    with pytest.raises(ValidationError):
        build_timeline_summary(_timeline(), asset_refs=_refs(), max_segments=0)


def test_summary_bounds_the_segment_count() -> None:
    segments = [
        {
            "id": f"s{i}",
            "scene_id": f"scene-{i}",
            "asset_id": 10,
            "timeline_start_seconds": float(i),
            "duration_seconds": 1.0,
        }
        for i in range(300)
    ]
    timeline = Timeline.model_validate(
        {"id": "big", "project_id": 1, "revision": 1, "segments": segments}
    )
    refs = {10: AssetSummaryRef(id=10, media_type="VIDEO", duration_seconds=1000.0)}
    with pytest.raises(ValidationError):
        build_timeline_summary(timeline, asset_refs=refs, max_segments=200)
