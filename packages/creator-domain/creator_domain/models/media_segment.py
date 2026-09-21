from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MediaSegment(BaseModel):
    """A placed media asset within a scene's timeline.

    Generic and reusable: multiple segments may belong to one scene, durations
    are positive and finite, and no short-only (60s / 3min) ceiling is imposed.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    scene_id: str = Field(min_length=1, max_length=100)
    asset_id: int = Field(ge=1)
    timeline_start_seconds: float = Field(ge=0, allow_inf_nan=False)
    duration_seconds: float = Field(gt=0, allow_inf_nan=False)
    trim_start_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    trim_end_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    fit_mode: str = Field(default="cover", max_length=50)
    transition: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _check_trims(self) -> MediaSegment:
        if (
            self.trim_start_seconds is not None
            and self.trim_end_seconds is not None
            and self.trim_start_seconds > self.trim_end_seconds
        ):
            raise ValueError("trim_start_seconds must be <= trim_end_seconds")
        return self

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> MediaSegment:
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
