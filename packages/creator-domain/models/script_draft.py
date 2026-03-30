from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class VisualOverride(BaseModel):
    type: Literal["prompt", "image_url", "none"]
    value: str | None = None


class ScriptSection(BaseModel):
    id: str
    type: str
    text: str
    display_text: str | None = None
    speaker: str | None = "host"
    duration: float | None = None
    turn_kind: str | None = None
    visual_override: VisualOverride | None = None


class ScriptDraft(BaseModel):
    id: int
    run_id: int
    source_type: Literal[
        "generated_by_model",
        "pasted_markdown",
        "uploaded_markdown",
        "edited_manually",
    ]
    markdown_content: str | None = None
    structured_script: list[ScriptSection] | None = None
    version: int = 1
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> "ScriptDraft":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
