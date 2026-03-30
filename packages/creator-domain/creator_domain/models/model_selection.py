from pydantic import BaseModel


class ModelSelection(BaseModel):
    script_model: str | None = None
    image_model: str | None = None
    tts_model: str | None = None
    subtitle_model: str | None = None
    render_profile: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "ModelSelection":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()
