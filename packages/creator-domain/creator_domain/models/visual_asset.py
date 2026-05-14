from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class VisualAsset(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", protected_namespaces=())

    id: int = Field(ge=1)
    run_id: int = Field(ge=1)
    scene_id: str = Field(max_length=100)
    version: int = Field(ge=0, default=1)
    asset_path: str
    prompt_snapshot: str | None = None
    model_used: str | None = Field(default=None, max_length=100)
    provider_type: str | None = Field(default=None, max_length=50)
    storage_provider: str | None = None
    storage_key: str | None = None
    is_active: bool = True
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> VisualAsset:
        return cls.model_validate(data)

    @classmethod
    def from_row(cls, row: dict[str, object]) -> VisualAsset:
        """Construct from a DB row dict, mapping column names to domain fields.

        Handles:
        - provider (VARCHAR) -> provider_type (str)
        """
        mapped = dict(row)
        if "provider" in mapped and "provider_type" not in mapped:
            mapped["provider_type"] = mapped.pop("provider")
        known = set(cls.model_fields)
        filtered = {key: value for key, value in mapped.items() if key in known}
        return cls.model_validate(filtered)

    def to_json(self) -> str:
        return self.model_dump_json()
