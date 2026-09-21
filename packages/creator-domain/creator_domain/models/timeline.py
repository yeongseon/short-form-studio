from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .media_segment import MediaSegment


class Timeline(BaseModel):
    """A project's editable, time-based content.

    One Timeline per Project, with stable identity and a monotonic revision.
    Segments are generic MediaSegments grouped by scene; timings must not
    overlap, and no short-only duration ceiling is imposed. There is no Sequence
    domain — a Timeline is the single top-level time container.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    project_id: int = Field(ge=1)
    revision: int = Field(ge=0, default=0)
    segments: list[MediaSegment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_segments(self) -> Timeline:
        seen: set[str] = set()
        for seg in self.segments:
            if seg.id in seen:
                raise ValueError(f"duplicate segment id: {seg.id!r}")
            seen.add(seg.id)

        ordered = sorted(self.segments, key=lambda s: s.timeline_start_seconds)
        prev_end = 0.0
        for seg in ordered:
            if seg.timeline_start_seconds + 1e-9 < prev_end:
                raise ValueError("segments must not overlap on the timeline")
            prev_end = seg.timeline_start_seconds + seg.duration_seconds
        return self

    def segments_by_scene(self) -> dict[str, list[MediaSegment]]:
        grouped: dict[str, list[MediaSegment]] = {}
        for seg in sorted(self.segments, key=lambda s: s.timeline_start_seconds):
            grouped.setdefault(seg.scene_id, []).append(seg)
        return grouped

    @property
    def total_duration_seconds(self) -> float:
        return max(
            (s.timeline_start_seconds + s.duration_seconds for s in self.segments),
            default=0.0,
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Timeline:
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
