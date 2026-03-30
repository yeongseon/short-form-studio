from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SubtitleArtifact(BaseModel):
    id: int
    run_id: int
    path: str
    format: Literal["srt", "vtt"] = "srt"
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> "SubtitleArtifact":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
