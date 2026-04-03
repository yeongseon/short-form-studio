from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Project(BaseModel):
    id: int
    title: str | None = None
    source_type: Literal["idea", "markdown", "pasted_json", "url"] = "idea"
    idea_brief: str | None = None
    markdown_source: str | None = None
    url_source: str | None = None
    json_script: str | None = None
    status: Literal["draft", "active", "completed", "archived"] = "draft"
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
