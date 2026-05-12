from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from .model_selection import ModelSelection


class PipelineRun(BaseModel):
    id: int
    project_id: int
    current_stage: str | None = None
    status: Literal["pending", "running", "paused", "completed", "failed", "cancelled"] = "pending"
    review_stage: str | None = None
    restart_from: str | None = None
    model_defaults: ModelSelection | None = None
    metadata: dict | None = None
    style_preset: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> PipelineRun:
        return cls.model_validate(data)

    @classmethod
    def from_row(cls, row: dict) -> PipelineRun:
        """Construct from a DB row dict, mapping column names to domain fields.

        Handles:
        - model_defaults_json (TEXT) -> model_defaults (ModelSelection | None)
        - metadata_json (TEXT) -> metadata (dict | None)
        """
        mapped = dict(row)
        raw_defaults = mapped.pop("model_defaults_json", None)
        if raw_defaults is not None:
            mapped["model_defaults"] = json.loads(raw_defaults)
        raw_meta = mapped.pop("metadata_json", None)
        if raw_meta is not None:
            mapped["metadata"] = json.loads(raw_meta)
        return cls.model_validate(mapped)

    def to_json(self) -> str:
        return self.model_dump_json()
