"""SF-54: bounded, secret-free Timeline summary for LLM editing.

build_timeline_summary produces a deterministic, bounded summary of a saved
Timeline revision for an LLM editor: stable scene/segment ids, timings,
authorized asset facts (kind/duration only — never storage keys or credentials),
and the base revision the summary is associated with. The summary is a pure
function of the timeline + supplied asset refs, so identical inputs yield
byte-identical output. Only the caller-supplied AssetSummaryRef fields are
included, so unauthorized storage data can never leak into the LLM context.
"""

from __future__ import annotations

from typing import Any, ClassVar

from creator_domain.exceptions import ValidationError
from creator_domain.models import Timeline
from pydantic import BaseModel, ConfigDict, Field

_DEFAULT_MAX_SEGMENTS = 500


class AssetSummaryRef(BaseModel):
    """The only asset facts allowed into an LLM summary.

    Deliberately excludes storage_key, source_url, credentials, and workspace
    internals — the caller resolves these from an authorized, workspace-scoped
    lookup, so nothing sensitive can reach the model context.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    media_type: str = Field(min_length=1, max_length=50)
    duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)


def build_timeline_summary(
    timeline: Timeline,
    *,
    asset_refs: dict[int, AssetSummaryRef],
    max_segments: int = _DEFAULT_MAX_SEGMENTS,
) -> dict[str, Any]:
    """Summarize a Timeline revision for an LLM editor (bounded, secret-free)."""
    if len(timeline.segments) > max_segments:
        raise ValidationError(
            f"timeline has {len(timeline.segments)} segments, exceeding the "
            f"summary bound of {max_segments}"
        )

    ordered = sorted(timeline.segments, key=lambda s: s.timeline_start_seconds)

    segments: list[dict[str, Any]] = []
    scenes: list[str] = []
    for segment in ordered:
        asset = asset_refs.get(segment.asset_id)
        if asset is None:
            raise ValidationError(
                f"segment {segment.id!r} references an unresolved asset"
            )
        if segment.scene_id not in scenes:
            scenes.append(segment.scene_id)
        segments.append(
            {
                "id": segment.id,
                "scene_id": segment.scene_id,
                "timeline_start_seconds": segment.timeline_start_seconds,
                "duration_seconds": segment.duration_seconds,
                "trim_start_seconds": segment.trim_start_seconds,
                "trim_end_seconds": segment.trim_end_seconds,
                "fit_mode": segment.fit_mode,
                "transition": segment.transition,
                "asset": {
                    "id": asset.id,
                    "media_type": asset.media_type,
                    "duration_seconds": asset.duration_seconds,
                },
            }
        )

    return {
        "timeline_id": timeline.id,
        "project_id": timeline.project_id,
        "base_revision": timeline.revision,
        "total_duration_seconds": timeline.total_duration_seconds,
        "scenes": scenes,
        "segments": segments,
    }
