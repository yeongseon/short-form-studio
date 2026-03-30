from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class VisualAsset(BaseModel):
    id: int
    run_id: int
    scene_id: str
    version: int = 1
    asset_path: str
    prompt_snapshot: str | None = None
    model_used: str | None = None
    provider_type: str | None = None
    is_active: bool = True
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> VisualAsset:
        return cls.model_validate(data)

    @classmethod
    def from_row(cls, row: dict) -> VisualAsset:
        """Construct from a DB row dict, mapping column names to domain fields.

        Handles:
        - provider (VARCHAR) -> provider_type (str)
        """
        mapped = dict(row)
        if "provider" in mapped and "provider_type" not in mapped:
            mapped["provider_type"] = mapped.pop("provider")
        return cls.model_validate(mapped)

    def to_json(self) -> str:
        return self.model_dump_json()
