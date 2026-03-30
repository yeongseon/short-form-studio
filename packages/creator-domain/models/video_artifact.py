from datetime import datetime

from pydantic import BaseModel


class VideoArtifact(BaseModel):
    id: int
    run_id: int
    path: str
    render_profile: str | None = None
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> "VideoArtifact":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
