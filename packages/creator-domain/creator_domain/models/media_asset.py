from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from .media_type import MediaOrigin, MediaType


class MediaAsset(BaseModel):
    """Generic media asset for the short-first, long-form-ready media core.

    Represents uploaded, generated, external, stock, or imported media without a
    short-only duration ceiling. Short form is a product constraint, not a core
    domain constraint, so this model stays media-first and reusable.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", protected_namespaces=())

    id: int = Field(ge=1)
    workspace_id: int = Field(ge=1)
    project_id: int | None = Field(default=None, ge=1)
    run_id: int | None = Field(default=None, ge=1)
    media_type: MediaType
    origin: MediaOrigin
    storage_key: str | None = Field(default=None, max_length=1024)
    mime_type: str | None = Field(default=None, max_length=255)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    source_url: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> MediaAsset:
        return cls.model_validate(data)

    @classmethod
    def from_row(cls, row: dict[str, object]) -> MediaAsset:
        """Construct from a DB row dict, dropping unknown columns."""
        known = set(cls.model_fields)
        filtered = {key: value for key, value in row.items() if key in known}
        return cls.model_validate(filtered)

    def to_json(self) -> str:
        return self.model_dump_json()
