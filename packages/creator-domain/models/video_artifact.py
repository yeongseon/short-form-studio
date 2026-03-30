from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class VideoArtifact(BaseModel):
    id: int
    run_id: int
    path: str
    render_profile: str | None = None
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> VideoArtifact:
        return cls.model_validate(data)

    @classmethod
    def from_row(cls, row: dict) -> VideoArtifact:
        """Construct from a DB row dict, mapping column names to domain fields.

        Handles:
        - file_path (TEXT) -> path (str)
        """
        mapped = dict(row)
        if "file_path" in mapped and "path" not in mapped:
            mapped["path"] = mapped.pop("file_path")
        # Discard DB-only columns not in this domain model
        mapped.pop("metadata_json", None)
        mapped.pop("artifact_type", None)
        mapped.pop("scene_id", None)
        mapped.pop("file_size_bytes", None)
        mapped.pop("mime_type", None)
        mapped.pop("updated_at", None)
        return cls.model_validate(mapped)

    def to_json(self) -> str:
        return self.model_dump_json()
