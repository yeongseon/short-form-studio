from __future__ import annotations

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
    def from_dict(cls, data: dict) -> AudioArtifact:
        return cls.model_validate(data)

    @classmethod
    def from_row(cls, row: dict) -> AudioArtifact:
        """Construct from a DB row dict, mapping column names to domain fields.

        Handles:
        - file_path (TEXT) -> path (str)
        - metadata_json (TEXT) -> ignored (not on this model)
        - provider (VARCHAR, if present) -> provider_type (str)
        """
        mapped = dict(row)
        if "file_path" in mapped and "path" not in mapped:
            mapped["path"] = mapped.pop("file_path")
        if "provider" in mapped and "provider_type" not in mapped:
            mapped["provider_type"] = mapped.pop("provider")
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
