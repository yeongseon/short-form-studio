from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Project(BaseModel):
    id: int
    workspace_id: int | None = None
    title: str | None = Field(default=None, max_length=200)
    source_type: Literal["idea", "markdown", "pasted_json", "url"] = "idea"
    idea_brief: str | None = None
    markdown_source: str | None = None
    url_source: str | None = None
    json_script: str | None = None
    status: Literal["draft", "active", "completed", "archived"] = "draft"
    workspace_id: int | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Project":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
