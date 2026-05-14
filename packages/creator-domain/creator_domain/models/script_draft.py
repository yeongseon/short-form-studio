from datetime import datetime
from typing import ClassVar
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VisualOverride(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    type: Literal["prompt", "image_url", "none"]
    value: str | None = None


class ScriptSection(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    section_id: str = Field(max_length=100)
    type: str
    text: str
    display_text: str | None = None
    speaker: str | None = "host"
    duration: float | None = None
    turn_kind: str | None = None
    visual_override: VisualOverride | None = None
    image_prompt: str | None = None
    mood: str | None = None
    composition: str | None = None
    style_tags: list[str] = Field(default_factory=list)


class ScriptDraft(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    run_id: int = Field(ge=1)
    source_type: Literal[
        "generated_by_model",
        "pasted_markdown",
        "uploaded_markdown",
        "edited_manually",
        "pasted_json",
    ]
    markdown_content: str | None = None
    structured_script: list[ScriptSection] | None = None
    version: int = Field(ge=0, default=1)
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ScriptDraft":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
