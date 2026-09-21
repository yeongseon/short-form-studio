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


class RenderSegmentKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class RenderSegment(BaseModel):
    """A renderer-facing, resolved media segment.

    Unlike the editor-facing MediaSegment (asset references, scene grouping),
    this carries a resolved media ``kind`` and ``source`` plus the placement and
    trims the renderer needs. Supports image and video without assuming one image
    per scene, and imposes no short-only duration ceiling.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    kind: RenderSegmentKind
    source: str = Field(min_length=1, max_length=1024)
    timeline_start_seconds: float = Field(ge=0, allow_inf_nan=False)
    duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    trim_start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    trim_end_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    fit_mode: str = Field(default="cover", max_length=50)
    transition: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _check_trims(self) -> RenderSegment:
        if (
            self.trim_start_seconds is not None
            and self.trim_end_seconds is not None
            and self.trim_start_seconds > self.trim_end_seconds
        ):
            raise ValueError("trim_start_seconds must be <= trim_end_seconds")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RenderSegment:
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
