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
    def from_dict(cls, data: dict) -> "PipelineRun":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
