from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class VisualScene(BaseModel):
    scene_id: str
    section_id: str
    scene_index: int
    section_type: str
    original_text: str
    prompt: str
    prompt_edited: bool = False
    prompt_source: Literal["auto_generated", "user_edited", "model_suggested"] = "auto_generated"
    style_tags: list[str] = Field(default_factory=list)
    mood: str | None = None
    composition: str | None = None
    generation_status: Literal["pending", "generating", "completed", "failed"] = "pending"
    latest_asset_id: int | None = None


class VisualPlan(BaseModel):
    id: int
    run_id: int
    version: int = 1
    scenes: list[VisualScene]
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> "VisualPlan":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
