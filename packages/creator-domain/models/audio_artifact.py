from datetime import datetime

from pydantic import BaseModel


class AudioArtifact(BaseModel):
    id: int
    run_id: int
    path: str
    model_used: str | None = None
    provider_type: str | None = None
    voice: str | None = None
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> "AudioArtifact":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
