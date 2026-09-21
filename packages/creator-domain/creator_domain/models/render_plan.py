from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .output_spec import EncodingProfile, OutputSpec
from .render_segment import RenderSegment


def _validate_relative_output_path(value: str | None) -> str | None:
    """Reject absolute or traversing paths.

    Render inputs must be authorized compiler/service outputs (workspace-relative
    artifact paths), never arbitrary absolute or ``..`` client paths.
    """
    if value is None:
        return None
    if not value:
        raise ValueError("path must not be empty")
    if value.startswith("/") or value.startswith("\\"):
        raise ValueError(f"path must be relative, got {value!r}")
    if "\x00" in value:
        raise ValueError("path contains null byte")
    parts = value.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError(f"path must not contain traversal, got {value!r}")
    return value


class RenderPlan(BaseModel):
    """A resolved, renderer-facing plan.

    Composes ordered RenderSegments, output geometry, and encoding settings, plus
    optional compiled narration/subtitle/music layers. Carries precise timing and
    no short/long product classification or duration ceiling.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    segments: list[RenderSegment] = Field(min_length=1)
    output_spec: OutputSpec
    encoding_profile: EncodingProfile
    narration_path: str | None = Field(default=None, max_length=1024)
    subtitle_path: str | None = Field(default=None, max_length=1024)
    music_path: str | None = Field(default=None, max_length=1024)

    @field_validator("narration_path", "subtitle_path", "music_path")
    @classmethod
    def _check_paths(cls, value: str | None) -> str | None:
        return _validate_relative_output_path(value)

    @model_validator(mode="after")
    def _check_non_overlapping(self) -> RenderPlan:
        ordered = sorted(self.segments, key=lambda s: s.timeline_start_seconds)
        prev_end = 0.0
        for seg in ordered:
            if seg.timeline_start_seconds + 1e-9 < prev_end:
                raise ValueError("segments must not overlap on the timeline")
            prev_end = seg.timeline_start_seconds + seg.duration_seconds
        return self

    @property
    def total_duration_seconds(self) -> float:
        return max(
            (s.timeline_start_seconds + s.duration_seconds for s in self.segments),
            default=0.0,
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RenderPlan:
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
