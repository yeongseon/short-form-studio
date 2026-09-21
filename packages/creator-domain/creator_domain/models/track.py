from __future__ import annotations

import sys
from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

if sys.version_info >= (3, 11):  # noqa: UP036
    from enum import StrEnum
else:

    class StrEnum(str, Enum):  # noqa: UP042
        def __str__(self) -> str:
            return self.value


class TrackRole(StrEnum):
    VISUAL = "visual"
    TEXT = "text"
    CAPTION = "caption"
    NARRATION = "narration"
    MUSIC = "music"


_TEXT_ROLES = frozenset({TrackRole.TEXT, TrackRole.CAPTION})
_MEDIA_ROLES = frozenset({TrackRole.VISUAL, TrackRole.NARRATION, TrackRole.MUSIC})


class TrackContent(BaseModel):
    """One placed item on a track.

    Carries exactly one of ``asset_id`` (media reference) or ``text`` (rendered
    directly), so text and captions never require a fake image asset.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    asset_id: int | None = Field(default=None, ge=1)
    text: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _check_exactly_one_source(self) -> TrackContent:
        if (self.asset_id is None) == (self.text is None):
            raise ValueError("content must carry exactly one of asset_id or text")
        return self

    @property
    def is_text(self) -> bool:
        return self.text is not None


class Track(BaseModel):
    """A single-role lane of ordered, non-overlapping content.

    One role per track (Visual, Text, Caption, Narration, Music). Text/Caption
    tracks hold text content; Visual/Narration/Music tracks hold media
    references. Advanced compositing and many stacked video layers are out of
    scope — this is a simple, flat track.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    role: TrackRole
    content: list[TrackContent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_content(self) -> Track:
        for item in self.content:
            if self.role in _TEXT_ROLES and not item.is_text:
                raise ValueError(f"{self.role.value} track requires text content")
            if self.role in _MEDIA_ROLES and item.is_text:
                raise ValueError(f"{self.role.value} track requires media content")

        ordered = sorted(self.content, key=lambda c: c.start_seconds)
        prev_end = 0.0
        for item in ordered:
            if item.start_seconds + 1e-9 < prev_end:
                raise ValueError("content must not overlap on the track")
            prev_end = item.start_seconds + item.duration_seconds
        return self

    def ordered_content(self) -> list[TrackContent]:
        return sorted(self.content, key=lambda c: c.start_seconds)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Track:
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
