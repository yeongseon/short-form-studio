from datetime import datetime
from typing import ClassVar
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VisualScene(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    scene_id: str = Field(max_length=100)
    section_id: str = Field(max_length=100)
    scene_index: int = Field(ge=0)
    section_type: str
    original_text: str
    prompt: str
    prompt_edited: bool = False
    prompt_source: Literal["auto_generated", "user_edited", "model_suggested"] = "auto_generated"
    style_tags: list[str] = Field(default_factory=list)
    mood: str | None = None
    composition: str | None = None
    generation_status: Literal["pending", "generating", "completed", "failed"] = "pending"
    latest_asset_id: int | None = Field(default=None, ge=1)


class VisualPlan(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    run_id: int = Field(ge=1)
    version: int = Field(ge=0, default=1)
    scenes: list[VisualScene]
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "VisualPlan":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
