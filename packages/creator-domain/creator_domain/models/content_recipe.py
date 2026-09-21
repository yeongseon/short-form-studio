from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DurationRange(BaseModel):
    """An inclusive [min, max] duration window in seconds."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    min_seconds: float = Field(gt=0)
    max_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def _check_order(self) -> DurationRange:
        if self.min_seconds > self.max_seconds:
            raise ValueError("min_seconds must be <= max_seconds")
        return self


class VisualStrategy(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    pacing: str = Field(max_length=50)
    segment_duration: DurationRange


class AudioSettings(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    narration: bool = True
    bgm: bool = False


class SubtitleSettings(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    enabled: bool = True
    emphasis: bool = False


class ContentRecipe(BaseModel):
    """Generic 'what to make' recipe for short-first, long-form-ready content.

    Defines target duration, content structure, visual strategy, and audio/
    subtitle settings. ``content_format`` is an optional, open string (not a
    closed short-only enum) so future formats (e.g. long-form) can be added
    without a schema change.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    target_duration: DurationRange
    structure: list[str] = Field(min_length=1)
    visual_strategy: VisualStrategy
    audio: AudioSettings
    subtitles: SubtitleSettings
    content_format: str | None = Field(default=None, max_length=50)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ContentRecipe:
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
